from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionParser, ActionValidationError
from .artifacts import FrozenSubmission
from .ledger import ResearchLedger


class ProtocolVerificationError(RuntimeError):
    pass


class ProtocolVerifier:
    def __init__(
        self,
        *,
        trajectory_root: Path,
        allowed_window_aliases: set[str],
        action_schema_path: Path,
    ):
        self.trajectory_root = trajectory_root
        self.allowed_window_aliases = set(allowed_window_aliases)
        self.action_parser = ActionParser(action_schema_path)

    def verify(self, submission: FrozenSubmission) -> dict[str, Any]:
        if submission.body.get("schema_version") != "0.2":
            raise ProtocolVerificationError("agentic submission must use schema_version=0.2")
        if submission.body["profile"] != "agentic_goal_loop":
            raise ProtocolVerificationError("submission is not agentic_goal_loop")
        summary = submission.body.get("search_summary") or {}
        required = {"task_id", "task_manifest_hash", "goal", "status", "trial_counts"}
        missing = sorted(required - set(summary))
        if missing:
            raise ProtocolVerificationError(
                "submission search summary missing: " + ", ".join(missing)
            )
        ledger_path = self.trajectory_root / submission.body["run_id"] / "agent" / "ledger.jsonl"
        ledger = ResearchLedger(
            ledger_path,
            task_id=summary["task_id"],
            task_manifest_hash=summary["task_manifest_hash"],
            goal=summary["goal"],
        )
        events = ledger.load_events()
        if len(events) < 2:
            raise ProtocolVerificationError("agentic ledger is incomplete")
        state = ledger.replay(events)
        action_audit = self._verify_model_action_provenance(events)
        self._verify_tool_result_envelopes(events)
        if not state.terminal:
            raise ProtocolVerificationError("replayed state is not terminal")
        if state.status != summary["status"]:
            raise ProtocolVerificationError("terminal status mismatch")
        if state.trial_counts != summary["trial_counts"]:
            raise ProtocolVerificationError("trial counts mismatch")
        if summary["task_manifest_hash"] != submission.body["hashes"].get("config_sha256"):
            raise ProtocolVerificationError("task manifest does not match frozen config")
        if int(summary.get("checkpoint_count", -1)) != len(state.checkpoints):
            raise ProtocolVerificationError("checkpoint count mismatch")
        if list(summary.get("submitted_evidence_ids") or []) != state.submitted_evidence_ids:
            raise ProtocolVerificationError("submitted evidence summary mismatch")
        if summary.get("conclusion") != state.conclusion:
            raise ProtocolVerificationError("conclusion summary mismatch")
        if list(summary.get("limitations") or []) != state.limitations:
            raise ProtocolVerificationError("limitations summary mismatch")
        if events[-1].event_type != "artifact_frozen":
            raise ProtocolVerificationError("last ledger event is not artifact_frozen")
        if events[-1].payload.get("submission_hash") != submission.submission_hash:
            raise ProtocolVerificationError("artifact event submission hash mismatch")
        expected_head = submission.body["hashes"].get("ledger_head_hash")
        if events[-2].event_hash != expected_head:
            raise ProtocolVerificationError("pre-freeze ledger head mismatch")
        if not submission.body["hashes"].get("harness_source_sha256"):
            raise ProtocolVerificationError("submission lacks Harness source fingerprint")
        submitted_ids = [factor["factor_id"] for factor in submission.body["factors"]]
        if submitted_ids != state.submitted_factor_ids:
            raise ProtocolVerificationError("submitted factor IDs mismatch")
        self._verify_submission_evidence(submission, state)
        unknown_evidence = [
            evidence_id
            for evidence_id in state.submitted_evidence_ids
            if evidence_id not in state.experiments
        ]
        if unknown_evidence:
            raise ProtocolVerificationError("submission references unknown evidence")
        invalid_windows = sorted(
            {
                experiment["window_alias"]
                for experiment in state.experiments.values()
                if experiment["window_alias"] not in self.allowed_window_aliases
            }
        )
        if invalid_windows:
            raise ProtocolVerificationError(
                "ledger contains forbidden window aliases: " + ", ".join(invalid_windows)
            )
        return {
            "status": "ok",
            "event_count": len(events),
            "final_state_version": state.state_version,
            "terminal_status": state.status,
            "trial_counts": dict(state.trial_counts),
            "submitted_factor_ids": submitted_ids,
            "submitted_evidence_ids": list(state.submitted_evidence_ids),
            "ledger_head_hash": events[-1].event_hash,
            "pre_freeze_ledger_head_hash": events[-2].event_hash,
            "model_action_audit": action_audit,
            "reference_factors": [
                {
                    "factor_id": factor_id,
                    "name": factor["name"],
                    "expression": factor["expression"],
                }
                for factor_id, factor in state.factors.items()
                if factor["hypothesis_id"] == "hyp_seed_pool"
            ],
        }

    def _verify_model_action_provenance(self, events: list) -> dict[str, int]:
        decision_types = {"propose", "evaluate", "refine", "pivot", "stop"}
        valid_actions = 0
        invalid_turns = 0
        for event in events:
            payload = event.payload
            raw_action = payload.get("model_action")
            if event.event_type in decision_types:
                if raw_action is None:
                    raise ProtocolVerificationError(
                        f"{event.event_type} event has no model action provenance"
                    )
                action = self._parse_action(raw_action)
                if action.action != event.event_type:
                    raise ProtocolVerificationError("model action and event type differ")
                if action.action_id != payload.get("action_id"):
                    raise ProtocolVerificationError("model action ID and event payload differ")
                valid_actions += 1
            elif event.event_type == "invalid_action":
                invalid_turns += 1
                if raw_action is not None:
                    action = self._parse_action(raw_action)
                    if action.action_id != payload.get("action_id"):
                        raise ProtocolVerificationError(
                            "rejected model action ID and event payload differ"
                        )
                elif not payload.get("raw_model_output") and not payload.get("errors"):
                    raise ProtocolVerificationError(
                        "invalid action has neither raw output nor structured errors"
                    )
        return {"valid_actions": valid_actions, "invalid_turns": invalid_turns}

    @staticmethod
    def _verify_tool_result_envelopes(events: list) -> None:
        result_types = {"propose", "evaluate", "refine", "pivot", "stop", "invalid_action"}
        for event in events:
            if event.event_type not in result_types:
                continue
            result = event.payload.get("observation")
            if not isinstance(result, dict) or result.get("schema_version") != "0.2":
                raise ProtocolVerificationError("research event lacks a v0.2 tool result")
            if result.get("action_id") != event.payload.get("action_id"):
                raise ProtocolVerificationError("tool result action ID mismatch")
            if result.get("state_version") != event.state_version:
                raise ProtocolVerificationError("tool result state version mismatch")
            checkpoint = result.get("checkpoint")
            if not isinstance(checkpoint, dict):
                raise ProtocolVerificationError("tool result lacks a checkpoint")

    def _parse_action(self, raw_action: dict[str, Any]):
        try:
            return self.action_parser.parse(raw_action)
        except ActionValidationError as exc:
            raise ProtocolVerificationError(
                "ledger contains an action that fails the frozen schema"
            ) from exc

    @staticmethod
    def _verify_submission_evidence(submission: FrozenSubmission, state) -> None:
        for submitted in submission.body["factors"]:
            factor_id = submitted["factor_id"]
            state_factor = state.factors[factor_id]
            for field in ("hypothesis_id", "parent_factor_id", "name", "expression", "direction"):
                if submitted.get(field) != state_factor.get(field):
                    raise ProtocolVerificationError(
                        f"submitted factor field differs from ledger: {factor_id}.{field}"
                    )
            evidence = submitted.get("search_evidence")
            if not isinstance(evidence, dict):
                raise ProtocolVerificationError("submitted factor lacks search_evidence")
            evidence_id = evidence.get("experiment_id")
            if evidence_id not in state.submitted_evidence_ids:
                raise ProtocolVerificationError("factor evidence was not selected by stop action")
            experiment = state.experiments.get(evidence_id)
            if not experiment or experiment["factor_id"] != factor_id:
                raise ProtocolVerificationError("factor evidence does not match submitted factor")
            if not experiment.get("success") or evidence.get("success") is not True:
                raise ProtocolVerificationError("submitted evidence is not successful")
            if evidence.get("window_alias") != experiment["window_alias"]:
                raise ProtocolVerificationError("submitted evidence window differs from ledger")
            if evidence.get("metrics") != experiment.get("metrics"):
                raise ProtocolVerificationError("submitted evidence metrics differ from ledger")
            if submitted.get("metrics") != experiment.get("metrics"):
                raise ProtocolVerificationError("submitted metrics differ from selected evidence")
