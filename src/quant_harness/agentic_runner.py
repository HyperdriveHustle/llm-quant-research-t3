from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actions import ActionParser, ActionValidationError
from .agent_policy import AgentPolicy
from .artifacts import FrozenSubmission, file_sha256, freeze_submission, harness_source_sha256
from .env import temporary_environ
from .ledger import ResearchLedger
from .runtime_paths import prepare_run_directory
from .state import ResearchState
from .state_projector import StateProjector
from .tool_gateway import GatewayExecution, ModelUsage, ToolGateway


class AgenticRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgenticRunnerConfig:
    task_id: str
    goal: str
    task_manifest_hash: str
    invalid_action_threshold: int
    safety_factor_evaluations: int
    emergency_model_turns: int | None
    checkpoint_evaluations: tuple[int, ...]
    max_submissions: int


class AgenticSearchRunner:
    def __init__(
        self,
        *,
        config: AgenticRunnerConfig,
        policy: AgentPolicy,
        action_parser: ActionParser,
        gateway: ToolGateway,
        projector: StateProjector,
        project_root: Path,
        run_root: Path,
        artifact_root: Path,
        trajectory_root: Path,
        config_path: Path,
        data_manifest_path: Path,
        upstream_commit: str,
        initial_factors: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
    ):
        self.config = config
        self.policy = policy
        self.action_parser = action_parser
        self.gateway = gateway
        self.projector = projector
        self.project_root = project_root
        self.run_root = run_root
        self.artifact_root = artifact_root
        self.trajectory_root = trajectory_root
        self.config_path = config_path
        self.data_manifest_path = data_manifest_path
        self.upstream_commit = upstream_commit
        self.initial_factors = list(initial_factors or [])
        self.harness_source_hash = harness_source_sha256(project_root)
        if gateway.safety_factor_evaluations != config.safety_factor_evaluations:
            raise ValueError("runner and ToolGateway evaluation ceilings differ")
        if projector.config.max_factor_evaluations != config.safety_factor_evaluations:
            raise ValueError("runner and StateProjector evaluation ceilings differ")
        if gateway.max_submissions != config.max_submissions:
            raise ValueError("runner and ToolGateway submission limits differ")
        if set(projector.config.allowed_window_aliases) != set(gateway.window_aliases):
            raise ValueError("StateProjector and ToolGateway window aliases differ")
        self.run_id = run_id or (f"agentic_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
        self.run_dir = run_root / self.run_id
        self.ledger_path = trajectory_root / self.run_id / "agent" / "ledger.jsonl"
        self.ledger = ResearchLedger(
            self.ledger_path,
            task_id=config.task_id,
            task_manifest_hash=config.task_manifest_hash,
            goal=config.goal,
        )

    def run(self) -> FrozenSubmission:
        prepare_run_directory(self.run_dir)
        model_log_dir = self.run_dir / "model_calls"
        state = ResearchState(
            task_id=self.config.task_id,
            task_manifest_hash=self.config.task_manifest_hash,
            goal=self.config.goal,
        )
        if self.initial_factors:
            _, state = self.ledger.append(
                event_type="bootstrap",
                payload={
                    "hypothesis_id": "hyp_seed_pool",
                    "hypothesis": {
                        "title": "Alpha158 reference seed pool",
                        "mechanism": "Reference factors from pinned paper runtime",
                        "predicted_direction": 1,
                        "falsification_rule": "Reference only",
                    },
                    "factors": copy.deepcopy(self.initial_factors),
                    "observation": {
                        "status": "bootstrapped",
                        "seed_factor_ids": [factor["factor_id"] for factor in self.initial_factors],
                    },
                },
                state=state,
            )
        runtime_env = {
            "HARNESS_RUNTIME_ROLE": "agent",
            "HARNESS_MODEL_LOG_DIR": str(model_log_dir),
        }
        with temporary_environ(runtime_env):
            while not state.terminal:
                if (
                    self.config.emergency_model_turns is not None
                    and state.trial_counts["model_calls"] >= self.config.emergency_model_turns
                ):
                    state = self._force_stop(state, "emergency model-turn ceiling reached")
                    break
                state_view = self.projector.project(state)
                try:
                    turn = self.policy.next_action(state_view)
                except Exception as exc:
                    state = self._append_invalid_policy_turn(
                        state,
                        usage=ModelUsage(model_calls=int(getattr(exc, "attempts", 1))),
                        errors=[{"code": "POLICY_ERROR", "message": str(exc)}],
                    )
                    if self._invalid_threshold_reached(state):
                        state = self._force_stop(state, "invalid action threshold reached")
                    continue
                try:
                    action = self.action_parser.parse(turn.action_text)
                except ActionValidationError as exc:
                    state = self._append_invalid_policy_turn(
                        state,
                        usage=turn.usage,
                        raw_model_output=turn.action_text,
                        response_id=turn.response_id,
                        errors=[
                            {
                                "code": "ACTION_SCHEMA_ERROR",
                                "message": str(exc),
                                "details": exc.errors,
                            }
                        ],
                    )
                    if self._invalid_threshold_reached(state):
                        state = self._force_stop(state, "invalid action threshold reached")
                    continue
                execution = self.gateway.execute(action, state, turn.usage)
                state = self._append_execution(
                    state,
                    action.action_id,
                    execution,
                    model_action=action.raw,
                    response_id=turn.response_id,
                )
                state = self._record_crossed_checkpoints(state)
        submission = self._freeze(state)
        _, final_state = self.ledger.append(
            event_type="artifact_frozen",
            payload={
                "submission_hash": submission.submission_hash,
                "submission_path": str(submission.path),
            },
            state=state,
        )
        (self.run_dir / "final_state.json").write_text(
            json.dumps(final_state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return submission

    def _append_execution(
        self,
        state: ResearchState,
        action_id: str,
        execution: GatewayExecution,
        model_action: dict[str, Any] | None = None,
        response_id: str | None = None,
    ) -> ResearchState:
        payload = copy.deepcopy(execution.event_payload)
        if model_action is not None:
            payload["model_action"] = copy.deepcopy(model_action)
        if response_id is not None:
            payload["response_id"] = response_id
        payload["observation"] = self._tool_result_envelope(
            state=state,
            action_id=action_id,
            execution=execution,
        )
        _, updated = self.ledger.append(
            event_type=execution.event_type,
            payload=payload,
            state=state,
        )
        return updated

    def _append_invalid_policy_turn(
        self,
        state: ResearchState,
        *,
        usage: ModelUsage,
        errors: list[dict[str, Any]],
        raw_model_output: str | None = None,
        response_id: str | None = None,
    ) -> ResearchState:
        action_id = f"invalid_{uuid.uuid4().hex}"
        raw_output_audit = self._raw_output_audit(raw_model_output)
        execution = GatewayExecution(
            event_type="invalid_action",
            event_payload={
                "action_id": action_id,
                "usage": usage.to_event(),
                "errors": errors,
                **raw_output_audit,
                "response_id": response_id,
            },
            status="rejected",
            observations={"status": "rejected", "errors": errors},
            registered_ids=[],
            protocol_flags=[
                {
                    "code": str(error["code"]),
                    "message": str(error["message"]),
                }
                for error in errors
            ],
        )
        return self._append_execution(state, action_id, execution)

    def _raw_output_audit(self, raw_model_output: str | None) -> dict[str, Any]:
        if raw_model_output is None:
            return {"raw_model_output": None}
        encoded = raw_model_output.encode("utf-8")
        limit = self.action_parser.max_payload_bytes
        prefix = encoded[:limit].decode("utf-8", errors="replace")
        return {
            "raw_model_output": prefix,
            "raw_model_output_bytes": len(encoded),
            "raw_model_output_sha256": hashlib.sha256(encoded).hexdigest(),
            "raw_model_output_truncated": len(encoded) > limit,
        }

    def _tool_result_envelope(
        self,
        *,
        state: ResearchState,
        action_id: str,
        execution: GatewayExecution,
    ) -> dict[str, Any]:
        usage = execution.event_payload.get("usage") or {}
        evaluation_delta = len(execution.event_payload.get("experiments") or [])
        factor_evaluations = state.trial_counts["factor_evaluations"] + evaluation_delta
        return {
            "schema_version": "0.2",
            "action_id": action_id,
            "status": execution.status,
            "state_version": state.state_version + 1,
            "observations": copy.deepcopy(execution.observations),
            "registered_ids": list(execution.registered_ids),
            "protocol_flags": copy.deepcopy(execution.protocol_flags),
            "checkpoint": {
                "factor_evaluations": factor_evaluations,
                "model_calls": state.trial_counts["model_calls"] + int(usage.get("model_calls", 0)),
                "logical_tokens": state.trial_counts["logical_tokens"]
                + int(usage.get("logical_tokens", 0)),
                "safety_ceiling_remaining": max(
                    self.config.safety_factor_evaluations - factor_evaluations,
                    0,
                ),
            },
        }

    def _record_crossed_checkpoints(self, state: ResearchState) -> ResearchState:
        completed = {int(checkpoint["factor_evaluations"]) for checkpoint in state.checkpoints}
        current = state.trial_counts["factor_evaluations"]
        for threshold in self.config.checkpoint_evaluations:
            if threshold > current or threshold in completed:
                continue
            checkpoint = {
                "factor_evaluations": threshold,
                "recorded_at_factor_evaluations": current,
                "source_state_version": state.state_version,
                "source_state_hash": state.state_hash,
                "model_calls": state.trial_counts["model_calls"],
                "logical_tokens": state.trial_counts["logical_tokens"],
                "best_factor_id": self._best_factor_id(state),
                "factor_ids": sorted(state.factors),
                "hypothesis_count": len(state.hypotheses),
                "active_hypothesis_count": sum(
                    hypothesis["status"] == "active" for hypothesis in state.hypotheses.values()
                ),
                "factor_count": len(state.factors),
                "max_factor_depth": self._max_factor_depth(state),
                "invalid_actions": state.trial_counts["invalid_actions"],
                "duplicates": state.trial_counts["duplicates"],
            }
            _, state = self.ledger.append(
                event_type="checkpoint",
                payload={"checkpoint": checkpoint},
                state=state,
            )
        return state

    def _force_stop(self, state: ResearchState, reason: str) -> ResearchState:
        _, updated = self.ledger.append(
            event_type="forced_stop",
            payload={"reason": reason},
            state=state,
        )
        return updated

    def _freeze(self, state: ResearchState) -> FrozenSubmission:
        selected_ids = state.submitted_factor_ids[: self.config.max_submissions]
        evidence_by_factor: dict[str, dict[str, Any]] = {}
        for evidence_id in state.submitted_evidence_ids:
            experiment = state.experiments[evidence_id]
            evidence_by_factor.setdefault(experiment["factor_id"], experiment)
        factors = []
        for factor_id in selected_ids:
            factor = state.factors[factor_id]
            evidence = evidence_by_factor[factor_id]
            metrics = copy.deepcopy(evidence["metrics"])
            factors.append(
                {
                    "factor_id": factor_id,
                    "hypothesis_id": factor["hypothesis_id"],
                    "parent_factor_id": factor.get("parent_factor_id"),
                    "name": factor["name"],
                    "expression": factor["expression"],
                    "direction": factor["direction"],
                    "metrics": metrics,
                    "search_evidence": {
                        "experiment_id": evidence["experiment_id"],
                        "window_alias": evidence["window_alias"],
                        "success": evidence["success"],
                        "metrics": copy.deepcopy(metrics),
                    },
                }
            )
        events = self.ledger.load_events()
        ledger_head_hash = events[-1].event_hash if events else "GENESIS"
        return freeze_submission(
            target=self.artifact_root / self.run_id / "submission.json",
            run_id=self.run_id,
            profile="agentic_goal_loop",
            factors=factors,
            hashes={
                "upstream_commit": self.upstream_commit,
                "config_sha256": file_sha256(self.config_path),
                "data_manifest_sha256": file_sha256(self.data_manifest_path),
                "harness_source_sha256": self.harness_source_hash,
                "ledger_head_hash": ledger_head_hash,
            },
            search_summary={
                "status": state.status,
                "task_id": state.task_id,
                "task_manifest_hash": state.task_manifest_hash,
                "goal": state.goal,
                "trial_counts": dict(state.trial_counts),
                "checkpoint_count": len(state.checkpoints),
                "submitted_evidence_ids": list(state.submitted_evidence_ids),
                "conclusion": state.conclusion,
                "limitations": list(state.limitations),
            },
            schema_version="0.2",
        )

    def _invalid_threshold_reached(self, state: ResearchState) -> bool:
        return state.trial_counts["invalid_actions"] >= self.config.invalid_action_threshold

    @staticmethod
    def _best_factor_id(state: ResearchState) -> str | None:
        rows = []
        for factor_id, factor in state.factors.items():
            for metrics in factor.get("metrics_by_window", {}).values():
                if "ic" in metrics:
                    rows.append((float(metrics["ic"]), factor_id))
        return max(rows, default=(float("-inf"), None))[1]

    @staticmethod
    def _max_factor_depth(state: ResearchState) -> int:
        depths: dict[str, int] = {}

        def depth(factor_id: str) -> int:
            if factor_id in depths:
                return depths[factor_id]
            parent_id = state.factors[factor_id].get("parent_factor_id")
            value = 0 if parent_id is None else depth(parent_id) + 1
            depths[factor_id] = value
            return value

        return max((depth(factor_id) for factor_id in state.factors), default=0)
