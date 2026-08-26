import json

import pytest

from quant_harness.ledger import LedgerIntegrityError, ResearchLedger
from quant_harness.state import ResearchState


def propose_payload():
    return {
        "usage": {"model_calls": 1, "logical_tokens": 100},
        "hypothesis_id": "hyp_1",
        "hypothesis": {
            "title": "momentum",
            "mechanism": "persistence",
            "predicted_direction": 1,
            "falsification_rule": "IC <= 0",
        },
        "factors": [
            {
                "factor_id": "factor_1",
                "hypothesis_id": "hyp_1",
                "name": "Momentum5",
                "expression": "Div($close, Ref($close, 5))",
                "direction": 1,
                "parent_factor_id": None,
            }
        ],
        "duplicates": [],
        "observation": {"status": "registered"},
    }


def test_ledger_replays_hash_chained_state(tmp_path):
    ledger = ResearchLedger(
        tmp_path / "ledger.jsonl",
        task_id="task",
        task_manifest_hash="manifest",
    )
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    _, state = ledger.append(event_type="propose", payload=propose_payload(), state=state)
    _, state = ledger.append(
        event_type="evaluate",
        payload={
            "usage": {"model_calls": 1, "logical_tokens": 50},
            "experiments": [
                {
                    "experiment_id": "exp_1",
                    "action_id": "a2",
                    "factor_id": "factor_1",
                    "window_alias": "search_full",
                    "metrics": {"ic": 0.04},
                    "success": True,
                    "expected_observation": "positive IC",
                    "decision_rule": "submit",
                }
            ],
            "observation": {"status": "evaluated"},
        },
        state=state,
    )
    replayed = ledger.replay()
    assert replayed.state_hash == state.state_hash
    assert replayed.factors["factor_1"]["metrics_by_window"]["search_full"]["ic"] == 0.04
    assert replayed.trial_counts["factor_evaluations"] == 1
    assert replayed.trial_counts["model_calls"] == 2


def test_ledger_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = ResearchLedger(path, task_id="task", task_manifest_hash="manifest")
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    ledger.append(event_type="propose", payload=propose_payload(), state=state)
    raw = json.loads(path.read_text().strip())
    raw["payload"]["hypothesis"]["title"] = "tampered"
    path.write_text(json.dumps(raw) + "\n")
    with pytest.raises(LedgerIntegrityError, match="hash mismatch"):
        ledger.load_events()


def test_invalid_action_counts_model_usage_without_factor_trials(tmp_path):
    ledger = ResearchLedger(
        tmp_path / "ledger.jsonl",
        task_id="task",
        task_manifest_hash="manifest",
    )
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    _, state = ledger.append(
        event_type="invalid_action",
        payload={
            "usage": {"model_calls": 1, "logical_tokens": 20},
            "errors": [{"message": "bad JSON"}],
        },
        state=state,
    )
    assert state.trial_counts["invalid_actions"] == 1
    assert state.trial_counts["factor_evaluations"] == 0
