from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .actions import ResearchAction
from .ffo import FactorResult, FFOClient
from .state import ResearchState


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 1

    @property
    def logical_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_event(self) -> dict[str, int]:
        return {"model_calls": self.model_calls, "logical_tokens": self.logical_tokens}


@dataclass(frozen=True)
class GatewayExecution:
    event_type: str
    event_payload: dict[str, Any]
    status: str
    observations: dict[str, Any]
    registered_ids: list[str]
    protocol_flags: list[dict[str, str]]
    terminal: bool = False


def default_id_factory(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ToolGateway:
    def __init__(
        self,
        *,
        search_client: FFOClient,
        market: str,
        label: str,
        instruments: str,
        window_aliases: dict[str, tuple[str, str]],
        check_period: tuple[str, str],
        max_candidates_per_action: int,
        max_submissions: int,
        safety_factor_evaluations: int,
        id_factory: Callable[[str], str] = default_id_factory,
    ):
        if search_client.role != "search":
            raise ValueError("ToolGateway requires a search-role FFO client")
        self.search_client = search_client
        self.market = market
        self.label = label
        self.instruments = instruments
        self.window_aliases = dict(window_aliases)
        self.check_period = check_period
        self.max_candidates_per_action = int(max_candidates_per_action)
        self.max_submissions = int(max_submissions)
        self.safety_factor_evaluations = int(safety_factor_evaluations)
        self.id_factory = id_factory

    def execute(
        self,
        action: ResearchAction,
        state: ResearchState,
        usage: ModelUsage,
    ) -> GatewayExecution:
        if state.terminal:
            return self._reject(action, usage, "TERMINAL_STATE", "episode is terminal")
        if action.action_id in state.processed_action_ids:
            return self._reject(
                action,
                usage,
                "DUPLICATE_ACTION_ID",
                "action_id was already processed",
            )
        if (
            state.trial_counts["factor_evaluations"] >= self.safety_factor_evaluations
            and action.action != "stop"
        ):
            return self._reject(
                action,
                usage,
                "SAFETY_FINALIZATION_REQUIRED",
                "factor-evaluation ceiling reached; the next valid action must be stop",
            )
        candidates = action.arguments.get("candidates")
        if isinstance(candidates, list) and len(candidates) > self.max_candidates_per_action:
            return self._reject(
                action,
                usage,
                "CANDIDATE_BATCH_TOO_LARGE",
                (
                    f"received {len(candidates)} candidates; maximum is "
                    f"{self.max_candidates_per_action}"
                ),
            )
        handler = getattr(self, f"_execute_{action.action}", None)
        if handler is None:
            return self._reject(action, usage, "UNSUPPORTED_ACTION", action.action)
        return handler(action, state, usage)

    def _execute_propose(
        self, action: ResearchAction, state: ResearchState, usage: ModelUsage
    ) -> GatewayExecution:
        hypothesis_id = self.id_factory("hyp")
        factors, duplicates, rejected = self._register_candidates(
            candidates=action.arguments["candidates"],
            state=state,
            hypothesis_id=hypothesis_id,
            parent_factor_id=None,
            edit_type="initial",
        )
        observation = {
            "status": "registered" if factors else "rejected",
            "hypothesis_id": hypothesis_id,
            "registered_factor_ids": [factor["factor_id"] for factor in factors],
            "duplicates": duplicates,
            "rejected_candidates": rejected,
        }
        payload = {
            "action_id": action.action_id,
            "usage": usage.to_event(),
            "hypothesis_id": hypothesis_id,
            "hypothesis": action.arguments["hypothesis"],
            "factors": factors,
            "duplicates": duplicates,
            "observation": observation,
        }
        return GatewayExecution(
            event_type="propose",
            event_payload=payload,
            status=observation["status"],
            observations=observation,
            registered_ids=[hypothesis_id] + [factor["factor_id"] for factor in factors],
            protocol_flags=self._rejection_flags(rejected),
        )

    def _execute_evaluate(
        self, action: ResearchAction, state: ResearchState, usage: ModelUsage
    ) -> GatewayExecution:
        hypothesis_id = action.hypothesis_id
        if hypothesis_id not in state.hypotheses:
            return self._reject(action, usage, "UNKNOWN_HYPOTHESIS", str(hypothesis_id))
        factor_ids = action.arguments["factor_ids"]
        unknown = [factor_id for factor_id in factor_ids if factor_id not in state.factors]
        if unknown:
            return self._reject(action, usage, "UNKNOWN_FACTOR", ", ".join(unknown))
        mismatched = [
            factor_id
            for factor_id in factor_ids
            if state.factors[factor_id]["hypothesis_id"] != hypothesis_id
        ]
        if mismatched:
            return self._reject(
                action,
                usage,
                "HYPOTHESIS_FACTOR_MISMATCH",
                ", ".join(mismatched),
            )
        alias = action.arguments["window_alias"]
        if alias not in self.window_aliases:
            return self._reject(action, usage, "UNKNOWN_WINDOW_ALIAS", alias)
        remaining = self.safety_factor_evaluations - state.trial_counts["factor_evaluations"]
        if len(factor_ids) > remaining:
            return self._reject(
                action,
                usage,
                "SAFETY_CEILING_EXCEEDED",
                f"requested {len(factor_ids)}, remaining {remaining}",
            )
        start, end = self.window_aliases[alias]
        factors = [
            {
                "name": state.factors[factor_id]["name"],
                "expression": state.factors[factor_id]["expression"],
            }
            for factor_id in factor_ids
        ]
        try:
            if len(factors) == 1:
                result_rows = [
                    self.search_client.evaluate(
                        factors[0]["expression"],
                        market=self.market,
                        start=start,
                        end=end,
                        label=self.label,
                    )
                ]
            else:
                result_rows = self.search_client.evaluate_batch(
                    factors,
                    market=self.market,
                    start=start,
                    end=end,
                    label=self.label,
                )
        except Exception as exc:
            result_rows = self._failed_results(factors, str(exc))
        if len(result_rows) < len(factors):
            result_rows = list(result_rows) + self._failed_results(
                factors[len(result_rows) :],
                "Search FFO returned fewer results than requested",
            )
        elif len(result_rows) > len(factors):
            result_rows = list(result_rows[: len(factors)])
        experiments = []
        for factor_id, result in zip(factor_ids, result_rows):
            experiments.append(
                {
                    "experiment_id": self.id_factory("exp"),
                    "action_id": action.action_id,
                    "hypothesis_id": hypothesis_id,
                    "factor_id": factor_id,
                    "window_alias": alias,
                    "metrics": dict(result.metrics),
                    "success": bool(result.success),
                    "error": result.error,
                    "expected_observation": action.expected_observation,
                    "decision_rule": action.decision_rule,
                }
            )
        observation = {
            "status": "evaluated",
            "window_alias": alias,
            "experiments": experiments,
        }
        return GatewayExecution(
            event_type="evaluate",
            event_payload={
                "action_id": action.action_id,
                "usage": usage.to_event(),
                "experiments": experiments,
                "observation": observation,
            },
            status="ok",
            observations=observation,
            registered_ids=[row["experiment_id"] for row in experiments],
            protocol_flags=[],
        )

    def _execute_refine(
        self, action: ResearchAction, state: ResearchState, usage: ModelUsage
    ) -> GatewayExecution:
        hypothesis_id = action.hypothesis_id
        parent_id = action.arguments["parent_factor_id"]
        if hypothesis_id not in state.hypotheses:
            return self._reject(action, usage, "UNKNOWN_HYPOTHESIS", str(hypothesis_id))
        if parent_id not in state.factors:
            return self._reject(action, usage, "UNKNOWN_PARENT", parent_id)
        if state.factors[parent_id]["hypothesis_id"] not in {
            hypothesis_id,
            "hyp_seed_pool",
        }:
            return self._reject(action, usage, "HYPOTHESIS_FACTOR_MISMATCH", parent_id)
        factors, duplicates, rejected = self._register_candidates(
            candidates=action.arguments["candidates"],
            state=state,
            hypothesis_id=hypothesis_id,
            parent_factor_id=parent_id,
            edit_type=action.arguments["edit_type"],
        )
        observation = {
            "status": "registered" if factors else "rejected",
            "parent_factor_id": parent_id,
            "registered_factor_ids": [factor["factor_id"] for factor in factors],
            "duplicates": duplicates,
            "rejected_candidates": rejected,
        }
        return GatewayExecution(
            event_type="refine",
            event_payload={
                "action_id": action.action_id,
                "usage": usage.to_event(),
                "factors": factors,
                "duplicates": duplicates,
                "observation": observation,
            },
            status=observation["status"],
            observations=observation,
            registered_ids=[factor["factor_id"] for factor in factors],
            protocol_flags=self._rejection_flags(rejected),
        )

    def _execute_pivot(
        self, action: ResearchAction, state: ResearchState, usage: ModelUsage
    ) -> GatewayExecution:
        old_id = action.arguments["from_hypothesis_id"]
        if old_id not in state.hypotheses:
            return self._reject(action, usage, "UNKNOWN_HYPOTHESIS", old_id)
        if state.hypotheses[old_id]["status"] != "active":
            return self._reject(action, usage, "HYPOTHESIS_NOT_ACTIVE", old_id)
        new_id = self.id_factory("hyp")
        factors, duplicates, rejected = self._register_candidates(
            candidates=action.arguments["candidates"],
            state=state,
            hypothesis_id=new_id,
            parent_factor_id=None,
            edit_type="pivot_initial",
        )
        observation = {
            "status": "pivoted",
            "closed_hypothesis_id": old_id,
            "new_hypothesis_id": new_id,
            "registered_factor_ids": [factor["factor_id"] for factor in factors],
            "duplicates": duplicates,
            "rejected_candidates": rejected,
        }
        return GatewayExecution(
            event_type="pivot",
            event_payload={
                "action_id": action.action_id,
                "usage": usage.to_event(),
                "from_hypothesis_id": old_id,
                "closure_status": action.arguments["closure_status"],
                "closure_reason": action.arguments["closure_reason"],
                "new_hypothesis_id": new_id,
                "new_hypothesis": action.arguments["new_hypothesis"],
                "factors": factors,
                "duplicates": duplicates,
                "observation": observation,
            },
            status="ok",
            observations=observation,
            registered_ids=[new_id] + [factor["factor_id"] for factor in factors],
            protocol_flags=self._rejection_flags(rejected),
        )

    def _execute_stop(
        self, action: ResearchAction, state: ResearchState, usage: ModelUsage
    ) -> GatewayExecution:
        arguments = action.arguments
        factor_ids = list(arguments["factor_ids"])
        evidence_ids = list(arguments["evidence_ids"])
        unknown_factors = [factor_id for factor_id in factor_ids if factor_id not in state.factors]
        unknown_evidence = [
            evidence_id for evidence_id in evidence_ids if evidence_id not in state.experiments
        ]
        if unknown_factors:
            return self._reject(action, usage, "UNKNOWN_FACTOR", ", ".join(unknown_factors))
        if unknown_evidence:
            return self._reject(action, usage, "UNKNOWN_EVIDENCE", ", ".join(unknown_evidence))
        if arguments["mode"] == "submit":
            if len(factor_ids) > self.max_submissions:
                return self._reject(
                    action,
                    usage,
                    "TOO_MANY_SUBMISSIONS",
                    f"received {len(factor_ids)}; maximum is {self.max_submissions}",
                )
            reference_seeds = [
                factor_id
                for factor_id in factor_ids
                if state.factors[factor_id]["hypothesis_id"] == "hyp_seed_pool"
            ]
            if reference_seeds:
                return self._reject(
                    action,
                    usage,
                    "REFERENCE_SEED_SUBMISSION",
                    ", ".join(reference_seeds),
                )
            unevaluated = [
                factor_id
                for factor_id in factor_ids
                if state.factors[factor_id]["status"] != "evaluated"
            ]
            if unevaluated:
                return self._reject(action, usage, "UNEVALUATED_SUBMISSION", ", ".join(unevaluated))
            evidenced_factor_ids = {
                state.experiments[evidence_id]["factor_id"] for evidence_id in evidence_ids
            }
            missing_evidence = [
                factor_id for factor_id in factor_ids if factor_id not in evidenced_factor_ids
            ]
            if missing_evidence:
                return self._reject(
                    action,
                    usage,
                    "FACTOR_WITHOUT_EVIDENCE",
                    ", ".join(missing_evidence),
                )
            failed_evidence = [
                evidence_id
                for evidence_id in evidence_ids
                if not state.experiments[evidence_id].get("success")
            ]
            if failed_evidence:
                return self._reject(
                    action,
                    usage,
                    "FAILED_EVIDENCE",
                    ", ".join(failed_evidence),
                )
        elif factor_ids or evidence_ids:
            return self._reject(
                action,
                usage,
                "NO_DISCOVERY_REFERENCES_OUTPUT",
                "no_discovery must not submit factors or evidence",
            )
        observation = {
            "status": "terminal",
            "mode": arguments["mode"],
            "factor_ids": factor_ids,
            "evidence_ids": evidence_ids,
        }
        return GatewayExecution(
            event_type="stop",
            event_payload={
                "action_id": action.action_id,
                "usage": usage.to_event(),
                "mode": arguments["mode"],
                "factor_ids": factor_ids,
                "evidence_ids": evidence_ids,
                "limitations": list(arguments["limitations"]),
                "conclusion": arguments.get("conclusion"),
                "observation": observation,
            },
            status="ok",
            observations=observation,
            registered_ids=[],
            protocol_flags=[],
            terminal=True,
        )

    def _register_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        state: ResearchState,
        hypothesis_id: str,
        parent_factor_id: str | None,
        edit_type: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
        existing = {
            self._normalize_expression(record["expression"]) for record in state.factors.values()
        }
        registered = []
        duplicates = []
        rejected = []
        seen_in_action = set()
        for candidate in candidates:
            expression = candidate["expression"]
            normalized = self._normalize_expression(expression)
            if normalized in existing or normalized in seen_in_action:
                duplicates.append(expression)
                continue
            seen_in_action.add(normalized)
            safety_error = self._expression_safety_error(expression)
            if safety_error:
                rejected.append(
                    {
                        "name": candidate["name"],
                        "code": "UNSAFE_EXPRESSION",
                        "message": safety_error,
                    }
                )
                continue
            try:
                check = self.search_client.check(
                    expression,
                    instruments=self.instruments,
                    start=self.check_period[0],
                    end=self.check_period[1],
                )
                if check.get("success") is not True:
                    rejected.append(
                        {
                            "name": candidate["name"],
                            "code": "DSL_CHECK_FAILED",
                            "message": self._safe_error_message(str(check)),
                        }
                    )
                    continue
            except Exception as exc:
                rejected.append(
                    {
                        "name": candidate["name"],
                        "code": "DSL_CHECK_ERROR",
                        "message": self._safe_error_message(str(exc)),
                    }
                )
                continue
            registered.append(
                {
                    "factor_id": self.id_factory("factor"),
                    "hypothesis_id": hypothesis_id,
                    "parent_factor_id": parent_factor_id,
                    "name": candidate["name"],
                    "expression": expression,
                    "direction": int(candidate["direction"]),
                    "rationale": candidate.get("rationale", ""),
                    "edit_type": edit_type,
                }
            )
        return registered, duplicates, rejected

    @staticmethod
    def _normalize_expression(expression: str) -> str:
        return re.sub(r"\s+", "", expression).lower()

    @staticmethod
    def _expression_safety_error(expression: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9_$.,()+\-*/\s]+", expression):
            return "expression contains characters outside the Qlib formula allowlist"
        lowered = expression.lower()
        forbidden = (
            "http:",
            "https:",
            "file:",
            "../",
            "__",
            "import",
            "exec(",
            "eval(",
            "open(",
            "system(",
            "subprocess",
            "socket",
            "requests",
            "urllib",
        )
        if any(token in lowered for token in forbidden):
            return "expression contains a forbidden code, path, or network token"
        return None

    @staticmethod
    def _safe_error_message(message: str) -> str:
        flattened = re.sub(r"[\r\n\t]+", " ", message)
        flattened = re.sub(r"https?://\S+", "[redacted-url]", flattened)
        flattened = re.sub(
            r"(?<![\w$])/(?:[^/\s]+/)+[^,\s)}\]]*",
            "[redacted-path]",
            flattened,
        )
        return flattened[:1000]

    @classmethod
    def _failed_results(
        cls,
        factors: list[dict[str, str]],
        message: str,
    ) -> list[FactorResult]:
        safe_message = cls._safe_error_message(message)
        return [
            FactorResult(
                name=factor["name"],
                expression=factor["expression"],
                success=False,
                metrics={},
                error=safe_message,
            )
            for factor in factors
        ]

    @staticmethod
    def _rejection_flags(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {"code": row["code"], "message": f"{row['name']}: {row['message']}"} for row in rows
        ]

    @staticmethod
    def _reject(
        action: ResearchAction,
        usage: ModelUsage,
        code: str,
        message: str,
    ) -> GatewayExecution:
        observation = {
            "status": "rejected",
            "code": code,
            "message": message,
        }
        return GatewayExecution(
            event_type="invalid_action",
            event_payload={
                "action_id": action.action_id,
                "usage": usage.to_event(),
                "errors": [{"code": code, "message": message}],
            },
            status="rejected",
            observations=observation,
            registered_ids=[],
            protocol_flags=[{"code": code, "message": message}],
        )
