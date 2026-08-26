import json
from pathlib import Path

import pytest

from quant_harness.actions import ActionParser, ActionValidationError


def parser():
    return ActionParser(Path("schemas/agent_action.schema.json"))


def test_parse_valid_propose_action():
    action = parser().parse(
        {
            "schema_version": "0.2",
            "action_id": "a1",
            "action": "propose",
            "reason": "test momentum",
            "expected_observation": "positive IC",
            "decision_rule": "refine if positive",
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
    assert action.action == "propose"
    assert action.arguments["candidates"][0]["name"] == "Momentum5"


def test_evaluate_requires_preregistered_expectation():
    with pytest.raises(ActionValidationError) as exc:
        parser().parse(
            {
                "schema_version": "0.2",
                "action_id": "a2",
                "action": "evaluate",
                "reason": "test",
                "hypothesis_id": "hyp_1",
                "arguments": {
                    "factor_ids": ["factor_1"],
                    "window_alias": "search_full",
                },
            }
        )
    assert any(error["message"].endswith("is a required property") for error in exc.value.errors)


def test_stop_no_discovery_needs_no_expectation_fields():
    action = parser().parse(
        json.dumps(
            {
                "schema_version": "0.2",
                "action_id": "a3",
                "action": "stop",
                "reason": "no evidence",
                "arguments": {
                    "mode": "no_discovery",
                    "factor_ids": [],
                    "evidence_ids": [],
                    "limitations": ["short sample"],
                    "conclusion": "No supported discovery",
                },
            }
        )
    )
    assert action.action == "stop"


def test_submit_requires_factor_and_evidence():
    with pytest.raises(ActionValidationError):
        parser().parse(
            {
                "schema_version": "0.2",
                "action_id": "a4",
                "action": "stop",
                "reason": "submit",
                "arguments": {
                    "mode": "submit",
                    "factor_ids": [],
                    "evidence_ids": [],
                    "limitations": [],
                },
            }
        )


def test_rejects_oversized_model_output():
    limited = ActionParser(Path("schemas/agent_action.schema.json"), max_payload_bytes=10)

    with pytest.raises(ActionValidationError, match="maximum payload size"):
        limited.parse("{}" + " " * 20)
