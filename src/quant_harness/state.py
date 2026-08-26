from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

TERMINAL_STATUSES = {"submitted", "no_discovery", "forced_stop"}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ResearchState:
    task_id: str
    task_manifest_hash: str
    goal: str = ""
    state_version: int = 0
    status: str = "researching"
    hypotheses: dict[str, dict[str, Any]] = field(default_factory=dict)
    factors: dict[str, dict[str, Any]] = field(default_factory=dict)
    experiments: dict[str, dict[str, Any]] = field(default_factory=dict)
    trial_counts: dict[str, int] = field(
        default_factory=lambda: {
            "model_calls": 0,
            "logical_tokens": 0,
            "factor_evaluations": 0,
            "invalid_actions": 0,
            "duplicates": 0,
        }
    )
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    processed_action_ids: list[str] = field(default_factory=list)
    submitted_factor_ids: list[str] = field(default_factory=list)
    submitted_evidence_ids: list[str] = field(default_factory=list)
    conclusion: str | None = None
    limitations: list[str] = field(default_factory=list)
    last_observation: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> ResearchState:
        return copy.deepcopy(self)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_manifest_hash": self.task_manifest_hash,
            "goal": self.goal,
            "state_version": self.state_version,
            "status": self.status,
            "hypotheses": copy.deepcopy(self.hypotheses),
            "factors": copy.deepcopy(self.factors),
            "experiments": copy.deepcopy(self.experiments),
            "trial_counts": dict(self.trial_counts),
            "checkpoints": copy.deepcopy(self.checkpoints),
            "processed_action_ids": list(self.processed_action_ids),
            "submitted_factor_ids": list(self.submitted_factor_ids),
            "submitted_evidence_ids": list(self.submitted_evidence_ids),
            "conclusion": self.conclusion,
            "limitations": list(self.limitations),
            "last_observation": copy.deepcopy(self.last_observation),
        }

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_dict())


class StateTransitionError(RuntimeError):
    pass


class StateReducer:
    """Pure event reducer for Agentic research state."""

    @staticmethod
    def apply(
        state: ResearchState,
        event_type: str,
        payload: dict[str, Any],
        *,
        next_version: int,
    ) -> ResearchState:
        if state.terminal and event_type not in {"artifact_frozen"}:
            raise StateTransitionError("terminal state cannot accept research events")
        if next_version != state.state_version + 1:
            raise StateTransitionError("state version must increase exactly once")
        updated = state.clone()
        usage = payload.get("usage") or {}
        updated.trial_counts["model_calls"] += int(usage.get("model_calls", 0))
        updated.trial_counts["logical_tokens"] += int(usage.get("logical_tokens", 0))
        action_id = payload.get("action_id")
        if action_id and event_type != "checkpoint":
            if action_id in updated.processed_action_ids:
                if event_type != "invalid_action":
                    raise StateTransitionError("action ID already processed")
            else:
                updated.processed_action_ids.append(action_id)

        if event_type == "bootstrap":
            hypothesis = copy.deepcopy(payload["hypothesis"])
            hypothesis_id = payload["hypothesis_id"]
            hypothesis.update(
                {
                    "hypothesis_id": hypothesis_id,
                    "status": "reference",
                    "created_version": next_version,
                }
            )
            updated.hypotheses[hypothesis_id] = hypothesis
            StateReducer._register_factors(updated, payload["factors"], next_version)
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "invalid_action":
            updated.trial_counts["invalid_actions"] += 1
            updated.last_observation = {
                "status": "rejected",
                "errors": copy.deepcopy(payload.get("errors") or []),
            }
        elif event_type == "propose":
            hypothesis = copy.deepcopy(payload["hypothesis"])
            hypothesis_id = payload["hypothesis_id"]
            if hypothesis_id in updated.hypotheses:
                raise StateTransitionError("hypothesis already exists")
            hypothesis.update(
                {
                    "hypothesis_id": hypothesis_id,
                    "status": "active",
                    "created_version": next_version,
                }
            )
            updated.hypotheses[hypothesis_id] = hypothesis
            StateReducer._register_factors(updated, payload["factors"], next_version)
            updated.trial_counts["duplicates"] += len(payload.get("duplicates") or [])
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "evaluate":
            experiments = payload["experiments"]
            for experiment in experiments:
                experiment_id = experiment["experiment_id"]
                if experiment_id in updated.experiments:
                    raise StateTransitionError("experiment already exists")
                updated.experiments[experiment_id] = copy.deepcopy(experiment)
                factor = updated.factors[experiment["factor_id"]]
                factor.setdefault("metrics_by_window", {})[experiment["window_alias"]] = (
                    copy.deepcopy(experiment["metrics"])
                )
                factor.setdefault("experiment_ids", []).append(experiment_id)
                factor["status"] = "evaluated"
            updated.trial_counts["factor_evaluations"] += len(experiments)
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "refine":
            StateReducer._register_factors(updated, payload["factors"], next_version)
            updated.trial_counts["duplicates"] += len(payload.get("duplicates") or [])
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "pivot":
            old = updated.hypotheses[payload["from_hypothesis_id"]]
            old["status"] = payload["closure_status"]
            old["closure_reason"] = payload["closure_reason"]
            old["closed_version"] = next_version
            new_hypothesis = copy.deepcopy(payload["new_hypothesis"])
            new_hypothesis_id = payload["new_hypothesis_id"]
            new_hypothesis.update(
                {
                    "hypothesis_id": new_hypothesis_id,
                    "status": "active",
                    "created_version": next_version,
                }
            )
            updated.hypotheses[new_hypothesis_id] = new_hypothesis
            StateReducer._register_factors(updated, payload["factors"], next_version)
            updated.trial_counts["duplicates"] += len(payload.get("duplicates") or [])
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "stop":
            mode = payload["mode"]
            updated.status = "submitted" if mode == "submit" else "no_discovery"
            updated.submitted_factor_ids = list(payload["factor_ids"])
            updated.submitted_evidence_ids = list(payload["evidence_ids"])
            updated.conclusion = payload.get("conclusion")
            updated.limitations = list(payload.get("limitations") or [])
            updated.last_observation = copy.deepcopy(payload["observation"])
        elif event_type == "forced_stop":
            updated.status = "forced_stop"
            updated.conclusion = payload["reason"]
            updated.last_observation = {"status": "forced_stop"}
        elif event_type == "checkpoint":
            updated.checkpoints.append(copy.deepcopy(payload["checkpoint"]))
        elif event_type == "artifact_frozen":
            updated.last_observation = copy.deepcopy(payload)
        else:
            raise StateTransitionError(f"unknown event type: {event_type}")

        updated.state_version = next_version
        return updated

    @staticmethod
    def _register_factors(
        state: ResearchState,
        factors: list[dict[str, Any]],
        state_version: int,
    ) -> None:
        for factor in factors:
            factor_id = factor["factor_id"]
            if factor_id in state.factors:
                raise StateTransitionError("factor already exists")
            record = copy.deepcopy(factor)
            record["status"] = "valid"
            record["created_version"] = state_version
            record["metrics_by_window"] = {}
            record["experiment_ids"] = []
            state.factors[factor_id] = record
