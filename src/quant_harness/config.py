from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Endpoint:
    role: str
    host: str
    port: int
    cache_path: Path

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class HarnessConfig:
    path: Path
    project_root: Path
    raw: dict[str, Any]
    search_endpoint: Endpoint
    verifier_endpoint: Endpoint

    @property
    def profile(self) -> str:
        return str(self.raw["profile"])

    @property
    def paper_result(self) -> bool:
        return bool(self.raw["paper_result"])

    @property
    def upstream_runtime(self) -> Path:
        return self.project_root / self.raw["upstream"]["paper_runtime"]

    @property
    def upstream_commit(self) -> str:
        return str(self.raw["upstream"]["full_commit_sha"])

    @property
    def provider_uri(self) -> Path:
        return self.project_root / self.raw["data"]["provider_uri"]

    @property
    def paper_period(self) -> tuple[str, str]:
        data = self.raw["data"]
        return str(data["start"]), str(data["end"])

    @property
    def model(self) -> dict[str, Any]:
        return self.raw["model"]

    @property
    def search(self) -> dict[str, Any]:
        return self.raw["search"]

    @property
    def run_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["run_root"]

    @property
    def artifact_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["artifact_root"]

    @property
    def trajectory_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["trajectory_root"]

    def validate(self, *, require_paths: bool = False) -> list[str]:
        errors: list[str] = []
        upstream = self.raw.get("upstream", {})
        if upstream.get("engine") != "qlib" or upstream.get("assay_enabled"):
            errors.append("paper_reproduction requires Qlib and assay_enabled=false")
        if not re.fullmatch(r"[0-9a-f]{40}", self.upstream_commit):
            errors.append("upstream.full_commit_sha must be a full 40-char SHA")
        if self.raw.get("data", {}).get("market") != "csi300":
            errors.append("strict T3 market must be csi300")
        if self.raw.get("data", {}).get("label") != "close_return":
            errors.append("strict T3 label must be close_return")
        allowed_algorithms = {"cot", "tot", "ea"}
        if self.profile == "agentic_goal_loop":
            allowed_algorithms.add("agentic")
        if self.search.get("algorithm") not in allowed_algorithms:
            errors.append("search.algorithm is incompatible with the selected profile")
        if self.profile == "agentic_goal_loop":
            errors.extend(self._validate_agentic())
        if self.paper_result and not self.raw.get("exact_paper_snapshot_verified", False):
            errors.append("paper_result=true requires exact_paper_snapshot_verified=true")
        if self.search_endpoint.base_url == self.verifier_endpoint.base_url:
            errors.append("search and verifier endpoints must differ")
        if self.search_endpoint.cache_path == self.verifier_endpoint.cache_path:
            errors.append("search and verifier caches must differ")
        for endpoint in (self.search_endpoint, self.verifier_endpoint):
            if endpoint.host not in {"127.0.0.1", "localhost"}:
                errors.append(f"{endpoint.role} endpoint must bind to loopback")
            try:
                endpoint.cache_path.relative_to(self.project_root)
            except ValueError:
                errors.append(f"{endpoint.role} cache must stay inside project")
        for name, enabled in self.raw.get("extensions", {}).items():
            if (
                self.profile
                in {
                    "paper_reproduction",
                    "paper_compatible_reproduction",
                }
                and enabled
            ):
                errors.append(f"extension {name} must be disabled in paper-compatible profiles")
        model = self.model

        def walk_keys(value: Any):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).lower()
                    yield from walk_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk_keys(child)

        forbidden_config_keys = {"api_key", "authorization", "auth_token", "password", "secret"}
        if any(key in forbidden_config_keys for key in walk_keys(self.raw)):
            errors.append("config must not contain literal credential fields")
        if model.get("provider") != "ark_coding_openai":
            errors.append("model.provider must be ark_coding_openai")
        if model.get("api_mode") not in {"responses", "chat_completions"}:
            errors.append("model.api_mode must be responses or chat_completions")
        max_output_tokens = model.get("max_output_tokens")
        if max_output_tokens is not None and (
            not isinstance(max_output_tokens, int) or max_output_tokens < 1
        ):
            errors.append("model.max_output_tokens must be a positive integer or null")
        fallback_tokens = model.get("fallback_max_output_tokens")
        if fallback_tokens is not None and (
            not isinstance(fallback_tokens, int) or fallback_tokens < 1
        ):
            errors.append("model.fallback_max_output_tokens must be a positive integer or null")
        for key in ("api_key_env", "base_url_env"):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(model.get(key, ""))):
                errors.append(f"model.{key} must name an environment variable")
        if require_paths:
            if not self.upstream_runtime.exists():
                errors.append(f"missing upstream runtime: {self.upstream_runtime}")
            if not self.provider_uri.exists():
                errors.append(f"missing Qlib data: {self.provider_uri}")
        return errors

    def _validate_agentic(self) -> list[str]:
        errors: list[str] = []
        agentic = self.raw.get("agentic")
        if not isinstance(agentic, dict):
            return ["agentic_goal_loop requires an agentic mapping"]
        required = {
            "task_id",
            "goal",
            "allowed_actions",
            "window_aliases",
            "check_period",
            "max_candidates_per_action",
            "safety",
            "checkpoints",
            "recent_event_window",
            "plateau_advisory_valid_evaluations",
        }
        missing = sorted(required - set(agentic))
        if missing:
            errors.append("agentic config missing: " + ", ".join(missing))
            return errors
        if not isinstance(agentic["task_id"], str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", agentic["task_id"]
        ):
            errors.append("agentic.task_id must be a stable identifier")
        if not isinstance(agentic["goal"], str) or not agentic["goal"].strip():
            errors.append("agentic.goal must be a non-empty string")
        canonical_actions = {"propose", "evaluate", "refine", "pivot", "stop"}
        configured_actions = agentic["allowed_actions"]
        if (
            not isinstance(configured_actions, list)
            or any(not isinstance(value, str) for value in configured_actions)
            or set(configured_actions) != canonical_actions
        ):
            errors.append("agentic.allowed_actions must contain the canonical five actions")
        aliases = agentic["window_aliases"]
        if not isinstance(aliases, dict) or not aliases:
            errors.append("agentic.window_aliases must be a non-empty mapping")
            aliases = {}
        unsupported_aliases = sorted(set(aliases) - {"search_full", "search_early", "search_late"})
        if unsupported_aliases:
            errors.append("unsupported search window aliases: " + ", ".join(unsupported_aliases))
        search_periods: list[tuple[date, date]] = []
        for alias, period in aliases.items():
            try:
                start, end = date.fromisoformat(str(period[0])), date.fromisoformat(str(period[1]))
            except (TypeError, ValueError, IndexError):
                errors.append(f"agentic.window_aliases.{alias} must be two ISO dates")
                continue
            if start > end:
                errors.append(f"agentic.window_aliases.{alias} start must not exceed end")
            search_periods.append((start, end))
        try:
            check_start = date.fromisoformat(str(agentic["check_period"][0]))
            check_end = date.fromisoformat(str(agentic["check_period"][1]))
            if check_start > check_end:
                errors.append("agentic.check_period start must not exceed end")
        except (TypeError, ValueError, IndexError):
            errors.append("agentic.check_period must be two ISO dates")
        max_candidates = agentic["max_candidates_per_action"]
        if not isinstance(max_candidates, int) or not 1 <= max_candidates <= 32:
            errors.append("agentic.max_candidates_per_action must be between 1 and 32")
        safety = agentic["safety"]
        safety_keys = {
            "invalid_action_threshold",
            "factor_evaluations",
            "emergency_model_turns",
        }
        if not isinstance(safety, dict) or not safety_keys.issubset(safety):
            errors.append("agentic.safety is incomplete")
        else:
            for key in {"invalid_action_threshold", "factor_evaluations"}:
                if not isinstance(safety[key], int) or safety[key] < 1:
                    errors.append(f"agentic.safety.{key} must be a positive integer")
            emergency_turns = safety["emergency_model_turns"]
            if emergency_turns is not None and (
                not isinstance(emergency_turns, int) or emergency_turns < 1
            ):
                errors.append(
                    "agentic.safety.emergency_model_turns must be null or a positive integer"
                )
            registration_stall = safety.get("registration_stall_actions", 10)
            if not isinstance(registration_stall, int) or registration_stall < 1:
                errors.append(
                    "agentic.safety.registration_stall_actions must be a positive integer"
                )
        checkpoints = agentic["checkpoints"]
        if (
            not isinstance(checkpoints, list)
            or any(not isinstance(value, int) or value < 1 for value in checkpoints)
            or checkpoints != sorted(set(checkpoints))
        ):
            errors.append("agentic.checkpoints must be sorted unique positive integers")
        elif isinstance(safety, dict) and isinstance(safety.get("factor_evaluations"), int):
            if checkpoints and checkpoints[-1] > safety["factor_evaluations"]:
                errors.append("agentic checkpoints cannot exceed the evaluation ceiling")
        if (
            not isinstance(self.search.get("max_submissions"), int)
            or self.search["max_submissions"] < 1
        ):
            errors.append("search.max_submissions must be a positive integer")
        for key in ("recent_event_window", "plateau_advisory_valid_evaluations"):
            if not isinstance(agentic[key], int) or agentic[key] < 1:
                errors.append(f"agentic.{key} must be a positive integer")
        outcome = self.raw.get("outcome_verification")
        if not isinstance(outcome, dict):
            errors.append("agentic_goal_loop requires outcome_verification")
        else:
            try:
                if outcome.get("role") != "hidden_oos":
                    errors.append("outcome_verification.role must be hidden_oos")
                outcome_start = date.fromisoformat(str(outcome["start"]))
                outcome_end = date.fromisoformat(str(outcome["end"]))
                if outcome_start > outcome_end:
                    errors.append("outcome_verification start must not exceed end")
                if any(outcome_start <= search_end for _, search_end in search_periods):
                    errors.append("outcome_verification must start after every search window")
                data_start = date.fromisoformat(str(self.raw["data"]["start"]))
                data_end = date.fromisoformat(str(self.raw["data"]["end"]))
                if any(start < data_start or end > data_end for start, end in search_periods):
                    errors.append("search windows must stay inside the declared data period")
                if outcome_start < data_start or outcome_end > data_end:
                    errors.append("outcome_verification must stay inside the declared data period")
            except (KeyError, TypeError, ValueError):
                errors.append("outcome_verification requires ISO start/end dates")
        if not self.raw.get("extensions", {}).get("controlled_oos"):
            errors.append("agentic_goal_loop requires extensions.controlled_oos=true")
        objective = self.raw.get("experiment_objective")
        if objective is not None:
            errors.extend(self._validate_experiment_objective(objective, set(aliases)))
        validation = self.raw.get("candidate_validation")
        if validation is not None:
            errors.extend(self._validate_candidate_validation(validation))
        return errors

    @staticmethod
    def _validate_candidate_validation(validation: Any) -> list[str]:
        if not isinstance(validation, dict):
            return ["candidate_validation must be a mapping"]
        policy = validation.get("policy")
        if policy not in {"strict", "coverage_aware"}:
            return ["candidate_validation.policy must be strict or coverage_aware"]
        errors = []
        if policy == "coverage_aware":
            for key in (
                "min_cross_section_coverage",
                "min_valid_date_fraction",
                "absolute_nan_cap",
            ):
                value = validation.get(key)
                if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                    errors.append(f"candidate_validation.{key} must be in [0, 1]")
        return errors

    def _validate_experiment_objective(
        self,
        objective: Any,
        window_aliases: set[str],
    ) -> list[str]:
        if not isinstance(objective, dict):
            return ["experiment_objective must be a mapping"]
        errors = []
        required_windows = objective.get("required_search_windows")
        if (
            not isinstance(required_windows, list)
            or not required_windows
            or any(alias not in window_aliases for alias in required_windows)
        ):
            errors.append("experiment_objective required windows are invalid")
        overrides = objective.get("min_direction_adjusted_search_ic_by_window") or {}
        if not isinstance(overrides, dict) or any(
            alias not in window_aliases for alias in overrides
        ):
            errors.append("experiment_objective window threshold overrides are invalid")
        for key in (
            "min_direction_adjusted_search_ic",
            "min_direction_adjusted_search_rank_ic",
            "min_direction_adjusted_hidden_oos_ic",
            "min_direction_adjusted_hidden_oos_rank_ic",
        ):
            if not isinstance(objective.get(key), (int, float)):
                errors.append(f"experiment_objective.{key} must be numeric")
        min_submissions = objective.get("min_submissions")
        if (
            not isinstance(min_submissions, int)
            or min_submissions < 1
            or min_submissions > self.search["max_submissions"]
        ):
            errors.append("experiment_objective.min_submissions is incompatible with search")
        min_hypotheses = objective.get("min_distinct_hypotheses", 1)
        if (
            not isinstance(min_hypotheses, int)
            or min_hypotheses < 1
            or isinstance(min_submissions, int)
            and min_hypotheses > min_submissions
        ):
            errors.append("experiment_objective.min_distinct_hypotheses is invalid")
        max_correlation = objective.get("max_mean_abs_output_correlation")
        if max_correlation is not None and (
            not isinstance(max_correlation, (int, float)) or not 0 <= float(max_correlation) <= 1
        ):
            errors.append("experiment_objective correlation threshold must be in [0, 1]")
        return errors

    def assert_valid(self, *, require_paths: bool = False) -> None:
        errors = self.validate(require_paths=require_paths)
        if errors:
            raise ConfigError("; ".join(errors))


def _endpoint(project_root: Path, role: str, raw: dict[str, Any]) -> Endpoint:
    return Endpoint(
        role=role,
        host=str(raw["host"]),
        port=int(raw["port"]),
        cache_path=project_root / str(raw["cache_path"]),
    )


def load_config(path: str | Path) -> HarnessConfig:
    config_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    project_root = config_path.parent.parent.resolve()
    required = ("profile", "paper_result", "upstream", "data", "model", "search", "runtime")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ConfigError(f"missing config keys: {', '.join(missing)}")
    runtime = raw["runtime"]
    cfg = HarnessConfig(
        path=config_path,
        project_root=project_root,
        raw=raw,
        search_endpoint=_endpoint(project_root, "search", runtime["search"]),
        verifier_endpoint=_endpoint(project_root, "verifier", runtime["verifier"]),
    )
    cfg.assert_valid(require_paths=False)
    return cfg
