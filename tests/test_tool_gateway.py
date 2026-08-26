from pathlib import Path

from quant_harness.actions import ActionParser
from quant_harness.ffo import FactorResult
from quant_harness.ledger import ResearchLedger
from quant_harness.state import ResearchState
from quant_harness.tool_gateway import ModelUsage, ToolGateway


class FakeFFO:
    role = "search"

    def check(self, expression, **kwargs):
        if "Invalid" in expression:
            return {"success": False}
        return {"success": True}

    def evaluate(self, expression, **kwargs):
        return FactorResult(
            name="factor",
            expression=expression,
            success=True,
            metrics={"ic": 0.04, "rank_ic": 0.03, "icir": 0.2},
        )

    def evaluate_batch(self, factors, **kwargs):
        return [
            FactorResult(
                name=factor["name"],
                expression=factor["expression"],
                success=True,
                metrics={"ic": 0.04, "rank_ic": 0.03, "icir": 0.2},
            )
            for factor in factors
        ]


class IDs:
    def __init__(self):
        self.counts = {}

    def __call__(self, prefix):
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}_{self.counts[prefix]}"


def action_parser():
    return ActionParser(Path("schemas/agent_action.schema.json"))


def gateway(ids):
    return ToolGateway(
        search_client=FakeFFO(),
        market="csi300",
        label="close_return",
        instruments="CSI300",
        window_aliases={"search_full": ("2020-01-01", "2022-12-31")},
        check_period=("2020-01-01", "2020-01-15"),
        max_candidates_per_action=32,
        max_submissions=2,
        safety_factor_evaluations=5,
        id_factory=ids,
    )


def propose_action(action_id="a1"):
    return action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": action_id,
            "action": "propose",
            "reason": "test momentum",
            "expected_observation": "positive IC",
            "decision_rule": "evaluate then refine",
            "arguments": {
                "hypothesis": {
                    "title": "momentum",
                    "mechanism": "persistence",
                    "predicted_direction": 1,
                    "falsification_rule": "IC <= 0",
                },
                "candidates": [
                    {
                        "name": "Momentum5",
                        "expression": "Div($close, Ref($close, 5))",
                        "direction": 1,
                    }
                ],
            },
        }
    )


def apply_execution(ledger, state, execution):
    _, updated = ledger.append(
        event_type=execution.event_type,
        payload=execution.event_payload,
        state=state,
    )
    return updated


def initialized(tmp_path):
    ids = IDs()
    gw = gateway(ids)
    ledger = ResearchLedger(
        tmp_path / "ledger.jsonl",
        task_id="task",
        task_manifest_hash="manifest",
    )
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    execution = gw.execute(propose_action(), state, ModelUsage(10, 5))
    state = apply_execution(ledger, state, execution)
    return ids, gw, ledger, state


def test_propose_evaluate_stop_flow(tmp_path):
    ids, gw, ledger, state = initialized(tmp_path)
    factor_id = next(iter(state.factors))
    hypothesis_id = next(iter(state.hypotheses))
    evaluate = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a2",
            "action": "evaluate",
            "reason": "test factor",
            "hypothesis_id": hypothesis_id,
            "expected_observation": "IC > 0",
            "decision_rule": "submit if IC > 0.03",
            "arguments": {
                "factor_ids": [factor_id],
                "window_alias": "search_full",
            },
        }
    )
    result = gw.execute(evaluate, state, ModelUsage(20, 10))
    state = apply_execution(ledger, state, result)
    evidence_id = next(iter(state.experiments))
    assert state.trial_counts["factor_evaluations"] == 1
    assert state.factors[factor_id]["status"] == "evaluated"

    stop = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a3",
            "action": "stop",
            "reason": "evidence sufficient",
            "arguments": {
                "mode": "submit",
                "factor_ids": [factor_id],
                "evidence_ids": [evidence_id],
                "limitations": ["search-only"],
                "conclusion": "submit",
            },
        }
    )
    result = gw.execute(stop, state, ModelUsage(5, 5))
    state = apply_execution(ledger, state, result)
    assert state.status == "submitted"
    assert state.submitted_factor_ids == [factor_id]


def test_unknown_window_and_duplicate_action_are_rejected(tmp_path):
    ids, gw, ledger, state = initialized(tmp_path)
    factor_id = next(iter(state.factors))
    hypothesis_id = next(iter(state.hypotheses))
    raw = {
        "schema_version": "0.2",
        "action_id": "a2",
        "action": "evaluate",
        "reason": "try hidden",
        "hypothesis_id": hypothesis_id,
        "expected_observation": "positive",
        "decision_rule": "continue",
        "arguments": {
            "factor_ids": [factor_id],
            "window_alias": "search_full",
        },
    }
    valid = action_parser().parse(raw)
    first = gw.execute(valid, state, ModelUsage())
    state = apply_execution(ledger, state, first)
    duplicate = gw.execute(valid, state, ModelUsage())
    assert duplicate.status == "rejected"
    assert duplicate.protocol_flags[0]["code"] == "DUPLICATE_ACTION_ID"


def test_no_discovery_is_first_class_terminal(tmp_path):
    ids, gw, ledger, state = initialized(tmp_path)
    factor_id = next(iter(state.factors))
    hypothesis_id = next(iter(state.hypotheses))
    evaluate = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a2",
            "action": "evaluate",
            "reason": "collect counter-evidence",
            "hypothesis_id": hypothesis_id,
            "expected_observation": "weak result",
            "decision_rule": "stop with no discovery if weak",
            "arguments": {
                "factor_ids": [factor_id],
                "window_alias": "search_full",
            },
        }
    )
    state = apply_execution(ledger, state, gw.execute(evaluate, state, ModelUsage()))
    evidence_id = next(iter(state.experiments))
    stop = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a3",
            "action": "stop",
            "reason": "hypothesis falsified",
            "arguments": {
                "mode": "no_discovery",
                "factor_ids": [],
                "evidence_ids": [evidence_id],
                "limitations": ["none"],
                "conclusion": "No supported discovery",
            },
        }
    )
    execution = gw.execute(stop, state, ModelUsage())
    state = apply_execution(ledger, state, execution)
    assert state.status == "no_discovery"
    assert state.submitted_evidence_ids == [evidence_id]


def test_invalid_and_duplicate_candidates_are_not_registered(tmp_path):
    ids = IDs()
    gw = gateway(ids)
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    action = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a1",
            "action": "propose",
            "reason": "test",
            "expected_observation": "positive",
            "decision_rule": "continue",
            "arguments": {
                "hypothesis": {
                    "title": "test",
                    "mechanism": "test",
                    "predicted_direction": 1,
                    "falsification_rule": "IC <= 0",
                },
                "candidates": [
                    {
                        "name": "Bad",
                        "expression": "Invalid($close)",
                        "direction": 1,
                    },
                    {
                        "name": "Good",
                        "expression": "Mean($close, 5)",
                        "direction": 1,
                    },
                    {
                        "name": "Duplicate",
                        "expression": " Mean( $close, 5 ) ",
                        "direction": 1,
                    },
                ],
            },
        }
    )
    execution = gw.execute(action, state, ModelUsage())
    assert len(execution.registered_ids) == 2
    assert any(flag["code"] == "DSL_CHECK_FAILED" for flag in execution.protocol_flags)
    assert execution.observations["duplicates"]


def test_candidate_batch_over_runtime_limit_is_rejected(tmp_path):
    ids = IDs()
    gw = gateway(ids)
    gw.max_candidates_per_action = 1
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    raw = {
        "schema_version": "0.2",
        "action_id": "a1",
        "action": "propose",
        "reason": "test the runtime ceiling",
        "expected_observation": "positive",
        "decision_rule": "continue",
        "arguments": {
            "hypothesis": {
                "title": "test",
                "mechanism": "test",
                "predicted_direction": 1,
                "falsification_rule": "IC <= 0",
            },
            "candidates": [
                {
                    "name": "First",
                    "expression": "Mean($close, 5)",
                    "direction": 1,
                },
                {
                    "name": "Second",
                    "expression": "Mean($close, 10)",
                    "direction": 1,
                },
            ],
        },
    }

    execution = gw.execute(action_parser().parse(raw), state, ModelUsage())

    assert execution.status == "rejected"
    assert execution.event_type == "invalid_action"
    assert execution.protocol_flags[0]["code"] == "CANDIDATE_BATCH_TOO_LARGE"


def test_code_or_network_tokens_are_rejected_before_ffo(tmp_path):
    ids = IDs()
    gw = gateway(ids)
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    raw = propose_action().raw
    raw["arguments"]["candidates"][0]["expression"] = "__import__(os).system(curl)"

    execution = gw.execute(action_parser().parse(raw), state, ModelUsage())

    assert execution.status == "rejected"
    assert execution.protocol_flags[0]["code"] == "UNSAFE_EXPRESSION"


def test_failed_evaluation_cannot_be_submission_evidence(tmp_path):
    class FailedFFO(FakeFFO):
        def evaluate(self, expression, **kwargs):
            return FactorResult(
                name="factor",
                expression=expression,
                success=False,
                metrics={},
                error="calculation failed",
            )

    ids = IDs()
    gw = gateway(ids)
    gw.search_client = FailedFFO()
    ledger = ResearchLedger(
        tmp_path / "ledger.jsonl",
        task_id="task",
        task_manifest_hash="manifest",
    )
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    proposed = gw.execute(propose_action(), state, ModelUsage())
    state = apply_execution(ledger, state, proposed)
    factor_id = next(iter(state.factors))
    hypothesis_id = next(iter(state.hypotheses))
    evaluate = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a2",
            "action": "evaluate",
            "reason": "collect evidence",
            "hypothesis_id": hypothesis_id,
            "expected_observation": "success",
            "decision_rule": "submit only if successful",
            "arguments": {
                "factor_ids": [factor_id],
                "window_alias": "search_full",
            },
        }
    )
    evaluated = gw.execute(evaluate, state, ModelUsage())
    state = apply_execution(ledger, state, evaluated)
    evidence_id = next(iter(state.experiments))
    stop = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a3",
            "action": "stop",
            "reason": "attempt submission",
            "arguments": {
                "mode": "submit",
                "factor_ids": [factor_id],
                "evidence_ids": [evidence_id],
                "limitations": [],
            },
        }
    )

    execution = gw.execute(stop, state, ModelUsage())

    assert execution.status == "rejected"
    assert execution.protocol_flags[0]["code"] == "FAILED_EVIDENCE"


def test_ffo_exception_becomes_failed_evidence_instead_of_aborting(tmp_path):
    class BrokenFFO(FakeFFO):
        def evaluate(self, expression, **kwargs):
            raise RuntimeError("failure at /private/secret/runtime/file.py")

    ids, gw, ledger, state = initialized(tmp_path)
    gw.search_client = BrokenFFO()
    factor_id = next(iter(state.factors))
    hypothesis_id = next(iter(state.hypotheses))
    evaluate = action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a2",
            "action": "evaluate",
            "reason": "collect evidence",
            "hypothesis_id": hypothesis_id,
            "expected_observation": "success",
            "decision_rule": "stop after failure",
            "arguments": {
                "factor_ids": [factor_id],
                "window_alias": "search_full",
            },
        }
    )

    execution = gw.execute(evaluate, state, ModelUsage())
    state = apply_execution(ledger, state, execution)
    experiment = next(iter(state.experiments.values()))

    assert experiment["success"] is False
    assert experiment["metrics"] == {}
    assert "/private/secret" not in experiment["error"]
    assert "[redacted-path]" in experiment["error"]


def submission_state():
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    state.hypotheses = {
        "hyp_seed_pool": {"status": "reference"},
        "hyp_1": {"status": "active"},
    }
    state.factors = {
        "seed_1": {
            "factor_id": "seed_1",
            "hypothesis_id": "hyp_seed_pool",
            "status": "evaluated",
        },
        "factor_1": {
            "factor_id": "factor_1",
            "hypothesis_id": "hyp_1",
            "status": "evaluated",
        },
    }
    state.experiments = {
        "exp_seed": {"factor_id": "seed_1", "success": True},
        "exp_candidate": {"factor_id": "factor_1", "success": True},
    }
    return state


def stop_action(*, factor_ids, evidence_ids):
    return action_parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "stop_1",
            "action": "stop",
            "reason": "freeze conclusion",
            "arguments": {
                "mode": "submit",
                "factor_ids": factor_ids,
                "evidence_ids": evidence_ids,
                "limitations": [],
            },
        }
    )


def test_submit_may_cite_successful_seed_baseline_as_auxiliary_evidence():
    gw = gateway(IDs())

    execution = gw.execute(
        stop_action(
            factor_ids=["factor_1"],
            evidence_ids=["exp_candidate", "exp_seed"],
        ),
        submission_state(),
        ModelUsage(),
    )

    assert execution.status == "ok"
    assert execution.event_type == "stop"


def test_reference_seed_cannot_be_submitted_as_new_discovery():
    gw = gateway(IDs())

    execution = gw.execute(
        stop_action(factor_ids=["seed_1"], evidence_ids=["exp_seed"]),
        submission_state(),
        ModelUsage(),
    )

    assert execution.status == "rejected"
    assert execution.protocol_flags[0]["code"] == "REFERENCE_SEED_SUBMISSION"
