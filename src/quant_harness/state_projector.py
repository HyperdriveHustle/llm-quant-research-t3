from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .objective import evaluate_search_objective
from .state import ResearchState


@dataclass(frozen=True)
class ProjectionConfig:
    allowed_actions: tuple[str, ...]
    allowed_window_aliases: tuple[str, ...]
    recent_event_window: int
    max_factor_evaluations: int
    plateau_advisory_valid_evaluations: int
    max_candidates_per_action: int = 32
    registration_stall_actions: int = 10
    experiment_objective: dict[str, Any] | None = None


class StateProjector:
    """Deterministic, model-visible projection of research state."""

    def __init__(self, config: ProjectionConfig):
        self.config = config

    def project(self, state: ResearchState) -> dict[str, Any]:
        factors = sorted(
            state.factors.values(),
            key=lambda factor: (
                self._best_ic(factor),
                factor.get("created_version", 0),
            ),
            reverse=True,
        )
        recent_experiments = [
            self._experiment_view(experiment)
            for experiment in list(state.experiments.values())[-self.config.recent_event_window :]
        ]
        evaluations_since_improvement = self._evaluations_since_best_improvement(state)
        evaluations_remaining = max(
            self.config.max_factor_evaluations - state.trial_counts["factor_evaluations"],
            0,
        )
        allowed_actions = (
            ["stop"] if evaluations_remaining == 0 else list(self.config.allowed_actions)
        )
        return {
            "schema_version": "0.2",
            "task": {
                "task_id": state.task_id,
                "task_manifest_hash": state.task_manifest_hash,
                "goal": state.goal,
            },
            "state_version": state.state_version,
            "status": state.status,
            "allowed_actions": allowed_actions,
            "allowed_window_aliases": list(self.config.allowed_window_aliases),
            "hypotheses": [
                self._hypothesis_view(hypothesis) for hypothesis in state.hypotheses.values()
            ],
            "top_factors": [self._factor_view(factor) for factor in factors[:20]],
            "recent_experiments": recent_experiments,
            "rejected_or_suspended_hypotheses": [
                self._closed_hypothesis_view(hypothesis)
                for hypothesis in state.hypotheses.values()
                if hypothesis["status"] in {"rejected", "suspended", "inconclusive"}
            ],
            "trial_counts": dict(state.trial_counts),
            "safety": {
                "factor_evaluation_ceiling": self.config.max_factor_evaluations,
                "factor_evaluations_remaining": evaluations_remaining,
                "finalization_required": evaluations_remaining == 0,
                "registration_stall_threshold": self.config.registration_stall_actions,
            },
            "protocol_limits": {
                "max_candidates_per_action": self.config.max_candidates_per_action,
            },
            "plateau_advisory": {
                "evaluations_since_best_ic_improvement": evaluations_since_improvement,
                "threshold": self.config.plateau_advisory_valid_evaluations,
                "active": evaluations_since_improvement
                >= self.config.plateau_advisory_valid_evaluations,
                "forces_stop": False,
            },
            "registration_stall_advisory": {
                "consecutive_empty_candidate_actions": state.trial_counts[
                    "consecutive_empty_candidate_actions"
                ],
                "threshold": self.config.registration_stall_actions,
                "active": state.trial_counts["consecutive_empty_candidate_actions"]
                >= max(1, self.config.registration_stall_actions // 2),
                "forces_stop": False,
            },
            "objective_progress": evaluate_search_objective(
                state,
                self.config.experiment_objective,
            ),
            "checkpoints": [
                self._checkpoint_view(checkpoint) for checkpoint in state.checkpoints[-5:]
            ],
            "last_observation": self._compact_value(state.last_observation),
        }

    @staticmethod
    def _best_ic(factor: dict[str, Any]) -> float:
        values = []
        for metrics in (factor.get("metrics_by_window") or {}).values():
            if "ic" in metrics:
                values.append(float(metrics["ic"]))
        return max(values, default=float("-inf"))

    @staticmethod
    def _factor_view(factor: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(factor)
        record.pop("rationale", None)
        experiment_ids = list(record.pop("experiment_ids", []))
        record["recent_experiment_ids"] = experiment_ids[-5:]
        record["experiment_count"] = len(experiment_ids)
        return record

    @staticmethod
    def _experiment_view(experiment: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(experiment.get(key))
            for key in (
                "experiment_id",
                "action_id",
                "hypothesis_id",
                "factor_id",
                "window_alias",
                "metrics",
                "success",
                "error",
            )
        }

    @staticmethod
    def _hypothesis_view(hypothesis: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(hypothesis.get(key))
            for key in (
                "hypothesis_id",
                "title",
                "mechanism",
                "predicted_direction",
                "falsification_rule",
                "status",
                "closure_reason",
                "created_version",
                "closed_version",
            )
            if key in hypothesis
        }

    @staticmethod
    def _closed_hypothesis_view(hypothesis: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(hypothesis.get(key))
            for key in (
                "hypothesis_id",
                "title",
                "status",
                "closure_reason",
                "closed_version",
            )
            if key in hypothesis
        }

    @staticmethod
    def _checkpoint_view(checkpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(checkpoint.get(key))
            for key in (
                "factor_evaluations",
                "recorded_at_factor_evaluations",
                "model_calls",
                "logical_tokens",
                "best_factor_id",
                "hypothesis_count",
                "active_hypothesis_count",
                "factor_count",
                "max_factor_depth",
                "invalid_actions",
                "duplicates",
            )
            if key in checkpoint
        }

    @staticmethod
    def _compact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: StateProjector._compact_value(child)
                for key, child in value.items()
                if key not in {"expected_observation", "decision_rule", "rationale"}
            }
        if isinstance(value, list):
            return [StateProjector._compact_value(child) for child in value]
        return copy.deepcopy(value)

    @staticmethod
    def _evaluations_since_best_improvement(state: ResearchState) -> int:
        best = float("-inf")
        last_improvement_index = 0
        rows = list(state.experiments.values())
        for index, experiment in enumerate(rows, start=1):
            metrics = experiment.get("metrics") or {}
            if experiment.get("success") and "ic" in metrics:
                ic = float(metrics["ic"])
                if ic > best:
                    best = ic
                    last_improvement_index = index
        return len(rows) - last_improvement_index
