from __future__ import annotations

import json

from quant_harness.model import (
    ArkModelClient,
    extract_response_text,
    extract_usage,
)


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_extract_responses_and_chat_shapes():
    responses = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "hello"}],
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    assert extract_response_text(responses) == "hello"
    assert extract_usage(responses) == (3, 2)
    chat = {
        "choices": [{"message": {"content": "world"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1},
    }
    assert extract_response_text(chat) == "world"
    assert extract_usage(chat) == (4, 1)


def test_model_call_logs_no_api_key(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        return FakeHTTPResponse(
            {
                "id": "resp_test",
                "output_text": '{"ok":true}',
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("HARNESS_MODEL_LOG_DIR", str(tmp_path))
    client = ArkModelClient(
        base_url="https://example.test/v3",
        api_key="test-secret-key",
        model="glm-5.3",
    )
    result = client.generate(
        prompt="test",
        system_prompt="json",
        temperature=0,
        json_output=True,
    )
    assert result.text == '{"ok":true}'
    logs = list(tmp_path.glob("*.json"))
    assert len(logs) == 1
    text = logs[0].read_text()
    assert "test-secret-key" not in text
    assert captured["authorization"] == "Bearer test-secret-key"
