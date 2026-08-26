from __future__ import annotations

import json

from quant_harness.config import load_config
from quant_harness.model import ModelResponse
from quant_harness.replay import replay_action_logs


def test_replay_validates_action_with_larger_output_budget(monkeypatch, tmp_path):
    call_log = tmp_path / "call.json"
    call_log.write_text(
        json.dumps(
            {
                "response_id": "old_response",
                "input_tokens": 100,
                "output_tokens": 32768,
                "response_text": '{"',
                "system_prompt": "return json",
                "prompt": "{}",
            }
        ),
        encoding="utf-8",
    )
    action = {
        "schema_version": "0.2",
        "action_id": "stop_1",
        "action": "stop",
        "reason": "no supported discovery",
        "arguments": {
            "mode": "no_discovery",
            "factor_ids": [],
            "evidence_ids": [],
            "limitations": ["test"],
            "conclusion": "none",
        },
    }

    class FakeClient:
        @classmethod
        def from_env(cls, **kwargs):
            return cls()

        def generate(self, **kwargs):
            assert kwargs["max_output_tokens"] == 65536
            return ModelResponse(
                text=json.dumps(action),
                response_id="new_response",
                input_tokens=100,
                output_tokens=1000,
                raw={},
                status="completed",
                requested_max_output_tokens=65536,
            )

    monkeypatch.setattr("quant_harness.replay.ArkModelClient", FakeClient)
    output_path = tmp_path / "replay.json"

    report = replay_action_logs(
        config=load_config("configs/real-t1-trend.yaml"),
        call_logs=[call_log],
        max_output_tokens=65536,
        output_path=output_path,
        timeout_seconds=1200,
    )

    assert report["schema_valid_count"] == 1
    assert report["timeout_seconds"] == 1200
    assert report["at_requested_limit_count"] == 0
    assert json.loads(output_path.read_text())["calls"][0]["response_status"] == "completed"
