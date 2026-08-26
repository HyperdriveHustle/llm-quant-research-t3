from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .artifacts import FrozenSubmission
from .config import HarnessConfig


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def live_run_progress(config: HarnessConfig, run_id: str) -> dict[str, Any]:
    ledger_path = config.trajectory_root / run_id / "agent" / "ledger.jsonl"
    if not ledger_path.exists():
        return {"run_id": run_id, "state": "initializing"}
    events = _load_ledger(ledger_path)
    model_calls = 0
    logical_tokens = 0
    factor_evaluations = 0
    for event in events:
        usage = event["payload"].get("usage") or {}
        model_calls += int(usage.get("model_calls", 0))
        logical_tokens += int(usage.get("logical_tokens", 0))
        factor_evaluations += len(event["payload"].get("experiments") or [])
    return {
        "run_id": run_id,
        "state": "running",
        "event_count": len(events),
        "last_sequence": events[-1]["sequence"],
        "last_event_type": events[-1]["event_type"],
        "model_turns": sum(
            event["event_type"]
            in {"propose", "evaluate", "refine", "pivot", "stop", "invalid_action"}
            for event in events
        ),
        "model_calls": model_calls,
        "logical_tokens": logical_tokens,
        "factor_evaluations": factor_evaluations,
        "elapsed_seconds": events[-1]["timestamp"] - events[0]["timestamp"],
    }


def analyze_agentic_run(
    *,
    config: HarnessConfig,
    run_id: str,
    submission_path: Path,
    verifier_report_path: Path,
) -> dict[str, Any]:
    ledger_path = config.trajectory_root / run_id / "agent" / "ledger.jsonl"
    events = _load_ledger(ledger_path)
    submission = FrozenSubmission.load(submission_path)
    verifier_report = json.loads(verifier_report_path.read_text(encoding="utf-8"))
    factors: dict[str, dict[str, Any]] = {}
    action_counts: Counter[str] = Counter()
    best_signed_ic: float | None = None
    optimization_timeline = []
    evaluation_index = 0
    cumulative_calls = 0
    cumulative_tokens = 0
    for event in events:
        payload = event["payload"]
        usage = payload.get("usage") or {}
        cumulative_calls += int(usage.get("model_calls", 0))
        cumulative_tokens += int(usage.get("logical_tokens", 0))
        if event["event_type"] in {
            "propose",
            "evaluate",
            "refine",
            "pivot",
            "stop",
            "invalid_action",
        }:
            action_counts[event["event_type"]] += 1
        for factor in payload.get("factors") or []:
            factors[factor["factor_id"]] = factor
        for experiment in payload.get("experiments") or []:
            evaluation_index += 1
            factor = factors.get(experiment["factor_id"], {})
            direction = int(factor.get("direction", 1))
            metrics = experiment.get("metrics") or {}
            signed_ic = (
                direction * float(metrics["ic"])
                if experiment.get("success") and "ic" in metrics
                else None
            )
            previous_best = best_signed_ic
            if signed_ic is not None and (best_signed_ic is None or signed_ic > best_signed_ic):
                best_signed_ic = signed_ic
            optimization_timeline.append(
                {
                    "evaluation_index": evaluation_index,
                    "sequence": event["sequence"],
                    "timestamp": event["timestamp"],
                    "action_id": payload.get("action_id"),
                    "hypothesis_id": experiment.get("hypothesis_id"),
                    "experiment_id": experiment["experiment_id"],
                    "factor_id": experiment["factor_id"],
                    "factor_name": factor.get("name"),
                    "is_reference_seed": factor.get("hypothesis_id") == "hyp_seed_pool",
                    "window_alias": experiment["window_alias"],
                    "success": experiment.get("success"),
                    "metrics": metrics,
                    "direction_adjusted_ic": signed_ic,
                    "best_direction_adjusted_ic": best_signed_ic,
                    "best_ic_improved": best_signed_ic != previous_best,
                    "cumulative_model_calls": cumulative_calls,
                    "cumulative_logical_tokens": cumulative_tokens,
                }
            )
    model_call_logs = []
    for path in sorted((config.run_root / run_id / "model_calls").glob("*.json")):
        model_call_logs.append(json.loads(path.read_text(encoding="utf-8")))
    latencies = [float(row["elapsed_seconds"]) for row in model_call_logs]
    summary = submission.body["search_summary"]
    objective_assessment = _assess_objective(
        config=config,
        submission=submission,
        verifier_report=verifier_report,
        events=events,
        factors=factors,
    )
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "task_id": summary["task_id"],
        "goal": summary["goal"],
        "terminal_status": summary["status"],
        "trial_counts": summary["trial_counts"],
        "model_turns": sum(action_counts.values()),
        "action_counts": dict(action_counts),
        "candidate_factor_count": sum(
            factor.get("hypothesis_id") != "hyp_seed_pool" for factor in factors.values()
        ),
        "hypothesis_count": len(
            {
                factor.get("hypothesis_id")
                for factor in factors.values()
                if factor.get("hypothesis_id") not in {None, "hyp_seed_pool"}
            }
        ),
        "elapsed_seconds_agent": events[-1]["timestamp"] - events[0]["timestamp"],
        "model_latency_seconds": {
            "count": len(latencies),
            "total": sum(latencies),
            "mean": statistics.fmean(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "max": max(latencies, default=None),
        },
        "best_direction_adjusted_search_ic": best_signed_ic,
        "optimization_timeline": optimization_timeline,
        "checkpoints": [
            event["payload"]["checkpoint"]
            for event in events
            if event["event_type"] == "checkpoint"
        ],
        "objective_assessment": objective_assessment,
        "verifier": {
            "verification_status": verifier_report.get("verification_status"),
            "research_outcome": verifier_report.get("research_outcome"),
            "metric_mismatch_count": len(verifier_report.get("metric_mismatches") or []),
        },
        "paths": {
            "ledger": str(ledger_path),
            "submission": str(submission_path),
            "verifier_report": str(verifier_report_path),
        },
    }


def _assess_objective(
    *,
    config: HarnessConfig,
    submission: FrozenSubmission,
    verifier_report: dict[str, Any],
    events: list[dict[str, Any]],
    factors: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    objective = config.raw.get("experiment_objective") or {}
    required_windows = list(objective.get("required_search_windows") or [])
    min_search_ic = float(objective.get("min_direction_adjusted_search_ic", 0.0))
    min_search_ic_by_window = {
        str(alias): float(value)
        for alias, value in (
            objective.get("min_direction_adjusted_search_ic_by_window") or {}
        ).items()
    }
    min_search_rank_ic = float(objective.get("min_direction_adjusted_search_rank_ic", 0.0))
    min_hidden_ic = float(objective.get("min_direction_adjusted_hidden_oos_ic", 0.0))
    min_hidden_rank_ic = float(objective.get("min_direction_adjusted_hidden_oos_rank_ic", 0.0))
    experiments = [
        experiment for event in events for experiment in (event["payload"].get("experiments") or [])
    ]
    best_search_seed_ic = max(
        (
            float(experiment["metrics"]["ic"])
            for experiment in experiments
            if factors.get(experiment["factor_id"], {}).get("hypothesis_id") == "hyp_seed_pool"
            and experiment["window_alias"] == "search_full"
            and experiment.get("success")
            and "ic" in experiment.get("metrics", {})
        ),
        default=None,
    )
    hidden_by_expression = {row["expression"]: row for row in verifier_report.get("factors") or []}
    factor_assessments = []
    for submitted in submission.body["factors"]:
        factor_id = submitted["factor_id"]
        direction = int(submitted.get("direction", 1))
        by_window = {}
        for alias in required_windows:
            rows = [
                experiment
                for experiment in experiments
                if experiment["factor_id"] == factor_id
                and experiment["window_alias"] == alias
                and experiment.get("success")
            ]
            best = max(
                rows,
                key=lambda row: direction * float((row.get("metrics") or {}).get("ic", -1e9)),
                default=None,
            )
            metrics = {} if best is None else best.get("metrics") or {}
            signed_ic = direction * float(metrics["ic"]) if "ic" in metrics else None
            signed_rank_ic = direction * float(metrics["rank_ic"]) if "rank_ic" in metrics else None
            by_window[alias] = {
                "experiment_id": None if best is None else best["experiment_id"],
                "direction_adjusted_ic": signed_ic,
                "direction_adjusted_rank_ic": signed_rank_ic,
                "minimum_direction_adjusted_ic": min_search_ic_by_window.get(alias, min_search_ic),
                "passes": bool(
                    signed_ic is not None
                    and signed_ic >= min_search_ic_by_window.get(alias, min_search_ic)
                    and signed_rank_ic is not None
                    and signed_rank_ic >= min_search_rank_ic
                ),
            }
        hidden = hidden_by_expression.get(submitted["expression"])
        hidden_metrics = {} if hidden is None else hidden.get("metrics") or {}
        hidden_ic = direction * float(hidden_metrics["ic"]) if "ic" in hidden_metrics else None
        hidden_rank_ic = (
            direction * float(hidden_metrics["rank_ic"]) if "rank_ic" in hidden_metrics else None
        )
        beats_seed = (
            best_search_seed_ic is not None
            and by_window.get("search_full", {}).get("direction_adjusted_ic") is not None
            and by_window["search_full"]["direction_adjusted_ic"] > best_search_seed_ic
        )
        factor_assessments.append(
            {
                "factor_id": factor_id,
                "name": submitted["name"],
                "search_windows": by_window,
                "beats_best_search_seed_ic": beats_seed,
                "hidden_oos": {
                    "direction_adjusted_ic": hidden_ic,
                    "direction_adjusted_rank_ic": hidden_rank_ic,
                    "passes": bool(
                        hidden is not None
                        and hidden.get("success")
                        and hidden_ic is not None
                        and hidden_ic >= min_hidden_ic
                        and hidden_rank_ic is not None
                        and hidden_rank_ic >= min_hidden_rank_ic
                    ),
                },
            }
        )
    min_submissions = int(objective.get("min_submissions", 1))
    min_distinct_hypotheses = int(objective.get("min_distinct_hypotheses", 1))
    require_seed_gain = bool(objective.get("require_beats_best_search_seed", True))
    diversity = verifier_report.get("output_correlation_diversity") or {}
    max_correlation = objective.get("max_mean_abs_output_correlation")
    diversity_passes = (
        True
        if max_correlation is None
        else diversity.get("mean_abs_correlation") is not None
        and float(diversity["mean_abs_correlation"]) <= float(max_correlation)
    )
    factors_pass = all(
        assessment["hidden_oos"]["passes"]
        and all(row["passes"] for row in assessment["search_windows"].values())
        and (assessment["beats_best_search_seed_ic"] or not require_seed_gain)
        for assessment in factor_assessments
    )
    distinct_hypothesis_count = len(
        {submitted["hypothesis_id"] for submitted in submission.body["factors"]}
    )
    return {
        "objective_id": objective.get("objective_id"),
        "discovery_achieved": bool(
            len(factor_assessments) >= min_submissions
            and distinct_hypothesis_count >= min_distinct_hypotheses
            and factors_pass
            and diversity_passes
        ),
        "valid_terminal_conclusion": submission.body["search_summary"]["status"]
        in {"submitted", "no_discovery"},
        "submitted_factor_count": len(factor_assessments),
        "minimum_submissions": min_submissions,
        "distinct_hypothesis_count": distinct_hypothesis_count,
        "minimum_distinct_hypotheses": min_distinct_hypotheses,
        "best_search_seed_ic": best_search_seed_ic,
        "factor_assessments": factor_assessments,
        "diversity": {
            "required_max_mean_abs_correlation": max_correlation,
            "observed": diversity,
            "passes": diversity_passes,
        },
    }
