from __future__ import annotations

import json
import urllib.error

import pytest

from quant_harness.model import (
    ArkModelClient,
    ModelError,
    extract_response_metadata,
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


def test_response_text_concatenates_multiple_content_blocks():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"action":'},
                    {"type": "output_text", "text": '"stop"}'},
                ],
            }
        ]
    }

    assert extract_response_text(payload) == '{"action":"stop"}'


def test_response_metadata_keeps_completion_diagnostics():
    metadata = extract_response_metadata(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "{"}],
                }
            ],
        }
    )

    assert metadata["status"] == "incomplete"
    assert metadata["incomplete_reason"] == "max_output_tokens"
    assert metadata["output_item_types"] == ("message",)
    assert metadata["content_block_types"] == ("output_text",)


def test_model_call_logs_no_api_key(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
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
        max_output_tokens=65536,
        thinking={"type": "disabled"},
        json_schema={"type": "object", "properties": {}},
    )
    assert result.text == '{"ok":true}'
    logs = list(tmp_path.glob("*.json"))
    assert len(logs) == 1
    text = logs[0].read_text()
    assert "test-secret-key" not in text
    assert captured["authorization"] == "Bearer test-secret-key"
    assert captured["payload"]["max_output_tokens"] == 65536
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"
    assert json.loads(logs[0].read_text())["requested_max_output_tokens"] == 65536


def test_model_response_counts_transport_attempts(monkeypatch):
    attempts = 0

    def flaky_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError("temporary")
        return FakeHTTPResponse(
            {
                "output_text": "ok",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    client = ArkModelClient(
        base_url="https://example.test/v3",
        api_key="test-secret-key",
        model="glm-5.3",
    )

    response = client.generate(
        prompt="test",
        system_prompt="test",
        temperature=0,
        max_attempts=2,
    )

    assert response.attempts == 2


def test_model_error_counts_failed_transport_attempts(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("temporary")),
    )
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    client = ArkModelClient(
        base_url="https://example.test/v3",
        api_key="test-secret-key",
        model="glm-5.3",
    )

    with pytest.raises(ModelError) as exc:
        client.generate(
            prompt="test",
            system_prompt="test",
            temperature=0,
            max_attempts=2,
        )

    assert exc.value.attempts == 2
