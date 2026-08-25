from __future__ import annotations

import contextlib
import importlib
import json
import os
import random
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .artifacts import FrozenSubmission, file_sha256, freeze_submission
from .config import HarnessConfig
from .env import temporary_environ
from .ffo import FFOClient
from .paper_metrics import summarize_factors
from .reporting import build_paper_search_report
from .trajectory import TrajectoryWriter


class PaperRuntimeError(RuntimeError):
    pass


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


@contextlib.contextmanager
def paper_import_context(runtime: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    runtime_str = str(runtime)
    added = runtime_str not in sys.path
    if added:
        sys.path.insert(0, runtime_str)
    os.chdir(runtime)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        if added and runtime_str in sys.path:
            sys.path.remove(runtime_str)


class PaperRunner:
    def __init__(
        self,
        config: HarnessConfig,
        *,
        search_client: FFOClient,
        run_id: str | None = None,
    ):
        if search_client.role != "search":
            raise ValueError("PaperRunner requires a search-role FFO client")
        self.config = config
        self.search_client = search_client
        self.run_id = run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.run_dir = config.run_root / self.run_id
        self.trajectory_path = config.trajectory_root / self.run_id / "agent" / "trajectory.jsonl"
        self.trajectory = TrajectoryWriter(self.trajectory_path)

    def verify_upstream(self) -> None:
        runtime = self.config.upstream_runtime
        if not runtime.exists():
            raise PaperRuntimeError(f"missing paper runtime: {runtime}")
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=runtime,
            text=True,
            capture_output=True,
            check=True,
        )
        actual = result.stdout.strip()
        if actual != self.config.upstream_commit:
            raise PaperRuntimeError(
                f"paper runtime commit mismatch: {actual} != {self.config.upstream_commit}"
            )

    def run(self) -> FrozenSubmission:
        self.config.assert_valid(require_paths=True)
        self.verify_upstream()
        self.run_dir.mkdir(parents=True, exist_ok=False)
        model_log_dir = self.run_dir / "model_calls"
        runtime_env = {
            "HARNESS_RUNTIME_ROLE": "agent",
            "HARNESS_MODEL_LOG_DIR": str(model_log_dir),
            "HARNESS_TRAJECTORY_PATH": str(self.trajectory_path),
            "ARK_API_MODE": str(self.config.model["api_mode"]),
            "ARK_MODEL": str(self.config.model["model_id"]),
            "FACTOR_API_URL": self.config.search_endpoint.base_url,
        }
        random.seed(int(self.config.raw.get("random_seed", 0)))
        self.trajectory.append(
            "run_started",
            {
                "run_id": self.run_id,
                "profile": self.config.profile,
                "algorithm": self.config.search["algorithm"],
                "upstream_commit": self.config.upstream_commit,
                "paper_result": self.config.paper_result,
            },
        )
        with temporary_environ(runtime_env):
            with paper_import_context(self.config.upstream_runtime):
                result, final_factors = self._run_upstream()
                parser_cls = importlib.import_module(
                    "agent.qlib_contrib.qlib_expr_parsing"
                ).FactorParser
                paper_report = build_paper_search_report(
                    algorithm=self.config.search["algorithm"],
                    raw_result=result,
                    final_factors=final_factors,
                    run_dir=self.run_dir,
                    threshold=float(self.config.raw["paper_metrics"]["effective_ic_threshold"]),
                    parser_cls=parser_cls,
                )
        safe_result = json_safe(result)
        (self.run_dir / "upstream_result.json").write_text(
            json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.run_dir / "paper_search_report.json").write_text(
            json.dumps(json_safe(paper_report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = summarize_factors(
            final_factors,
            threshold=float(self.config.raw["paper_metrics"]["effective_ic_threshold"]),
        )
        summary["paper_search_metrics"] = json_safe(paper_report)
        hashes = self._hashes()
        submission = freeze_submission(
            target=self.config.artifact_root / self.run_id / "submission.json",
            run_id=self.run_id,
            profile=self.config.profile,
            factors=final_factors,
            hashes=hashes,
            search_summary=summary,
        )
        self.trajectory.append(
            "artifact_frozen",
            {
                "submission_hash": submission.submission_hash,
                "factor_count": len(final_factors),
            },
        )
        self.trajectory.append("run_ended", {"status": "completed"})
        return submission

    def _load_seeds(self) -> list[dict[str, Any]]:
        module = importlib.import_module("factors.lib.alpha158")
        _, compiled = module.load_factors_alpha158(
            exclude_var=self.config.search.get("exclude_variable"),
            collection=self.config.search["seed_collections"],
        )
        seeds = [
            {
                "name": item["name"],
                "expression": item.get("qlib_expression_default") or item.get("qlib_expression"),
            }
            for item in compiled.values()
        ]
        max_seeds = self.config.search.get("max_seeds")
        if max_seeds is not None:
            seeds = seeds[: int(max_seeds)]
        if not seeds:
            raise PaperRuntimeError("Alpha158 seed pool is empty")
        self.trajectory.append(
            "seed_loaded",
            {
                "count": len(seeds),
                "collections": self.config.search["seed_collections"],
                "names": [seed["name"] for seed in seeds],
            },
        )
        return seeds

    def _eval_one(self, expression: str) -> dict[str, Any]:
        start, end = self.config.paper_period
        try:
            result = self.search_client.evaluate(
                expression,
                market=self.config.raw["data"]["market"],
                start=start,
                end=end,
                label=self.config.raw["data"]["label"],
            )
        except Exception as exc:
            return {
                "success": False,
                "expression": expression,
                "metrics": {},
                "error": str(exc),
            }
        return {
            "success": result.success,
            "expression": result.expression,
            "metrics": result.metrics,
            "error": result.error,
        }

    def _eval_batch_list(self, factors: list[dict[str, str]]) -> list[dict[str, Any]]:
        start, end = self.config.paper_period
        try:
            results = self.search_client.evaluate_batch(
                factors,
                market=self.config.raw["data"]["market"],
                start=start,
                end=end,
                label=self.config.raw["data"]["label"],
            )
        except Exception as exc:
            return [
                {
                    "name": factor.get("name", ""),
                    "expression": factor.get("expression", ""),
                    "success": False,
                    "metrics": {},
                    "error": str(exc),
                }
                for factor in factors
            ]
        return [
            {
                "name": result.name,
                "expression": result.expression,
                "success": result.success,
                "metrics": result.metrics,
                "error": result.error,
            }
            for result in results
        ]

    def _eval_batch_dict(self, factors: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        return {row["name"]: row for row in self._eval_batch_list(factors)}

    def _run_upstream(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        seeds = self._load_seeds()
        search_fn = importlib.import_module("agent.generator_qlib_search").call_qlib_search
        search = self.config.search
        model = self.config.model
        algorithm = search["algorithm"]
        common = {
            "model": model["model_id"],
            "temperature": float(model["temperature"]),
            "enable_reason": bool(search.get("enable_reason", True)),
            "local": False,
            "local_port": 0,
        }
        algo_dir = self.run_dir / algorithm
        algo_dir.mkdir(parents=True, exist_ok=True)
        if algorithm == "ea":
            rows = self._eval_batch_list(seeds)
            for seed, row in zip(seeds, rows):
                seed["metrics"] = row["metrics"]
            cls = importlib.import_module("searcher.EA.EA_searcher").EA_Searcher
            runner = cls(
                batch_evaluate_factors_fn=self._eval_batch_list,
                search_fn=search_fn,
                save_dir=str(algo_dir),
                seeds_top_k=int(search["ea"]["seeds_top_k"]),
                **common,
            )
            raw = runner.search_population(
                seeds,
                mutation_rate=float(search["ea"]["mutation_rate"]),
                crossover_rate=float(search["ea"]["crossover_rate"]),
                N=int(search["ea"]["generate_size"]),
                rounds=int(search["ea"]["generations"]),
                verbose=False,
                save_pickle=True,
                pool_size=int(search["ea"]["population_size"]),
            )
            final = list(raw.get("final_pool") or [])
        elif algorithm == "cot":
            cls = importlib.import_module("searcher.CoT.CoT_searcher").CoTSearcher
            raw_runs = []
            final = []
            for seed in seeds:
                runner = cls(
                    evaluate_factor_fn=self._eval_one,
                    search_fn=search_fn,
                    save_dir=str(algo_dir),
                    **common,
                )
                result = runner.search_single_factor(
                    seed,
                    rounds=int(search["cot"]["rounds"]),
                    run_name=seed["name"],
                    verbose=False,
                    save_pickle=True,
                    save_dir=str(algo_dir),
                )
                raw_runs.append(result)
                final.append(result["best"])
            raw = {"runs": raw_runs, "final_pool": final}
        else:
            cls = importlib.import_module("searcher.ToT.ToT_searcher").ToTSearcher
            raw_runs = []
            final = []
            for seed in seeds:
                runner = cls(
                    evaluate_factor_fn=self._eval_one,
                    batch_evaluate_factors_fn=self._eval_batch_dict,
                    search_fn=search_fn,
                    save_dir=str(algo_dir),
                    top_k=int(search["tot"]["top_k"]),
                    **common,
                )
                result = runner.search_single_factor(
                    seed,
                    rounds=int(search["tot"]["rounds"]),
                    N=int(search["tot"]["candidates_per_node"]),
                    run_name=seed["name"],
                    verbose=False,
                    save_pickle=True,
                    save_dir=str(algo_dir),
                )
                raw_runs.append(result)
                final.append(result["best"])
            raw = {"runs": raw_runs, "final_pool": final}
        ranked = sorted(
            final,
            key=lambda item: float((item.get("metrics") or {}).get("ic", -1e9)),
            reverse=True,
        )
        limit = int(search["max_submissions"])
        return raw, json_safe(ranked[:limit])

    def _hashes(self) -> dict[str, str]:
        manifest = self.config.project_root / self.config.raw["data"]["snapshot_manifest"]
        trajectory_hash = file_sha256(self.trajectory_path)
        return {
            "upstream_commit": self.config.upstream_commit,
            "config_sha256": file_sha256(self.config.path),
            "data_manifest_sha256": (
                file_sha256(manifest) if manifest.exists() else "MISSING_UNVERIFIED"
            ),
            "trajectory_sha256_before_freeze": trajectory_hash,
        }
