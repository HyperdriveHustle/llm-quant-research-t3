from __future__ import annotations

import pytest

from quant_harness.ffo import FFOClient


def test_ffo_client_requires_explicit_role():
    with pytest.raises(ValueError, match="role"):
        FFOClient("http://127.0.0.1:1", role="agent")


def test_ffo_client_normalizes_single_and_batch(monkeypatch):
    client = FFOClient("http://127.0.0.1:1", role="search")

    def fake_request(path, payload=None):
        if path == "/eval":
            return {"success": True, "metrics": {"ic": 0.1}}
        return {
            "success": True,
            "results": [{"name": "f1", "success": True, "metrics": {"ic": 0.2}}],
        }

    monkeypatch.setattr(client, "_request", fake_request)
    single = client.evaluate(
        "$close", market="csi300", start="2020-01-01", end="2020-02-01", label="close_return"
    )
    assert single.metrics["ic"] == 0.1
    batch = client.evaluate_batch(
        [{"name": "f1", "expression": "$close"}],
        market="csi300",
        start="2020-01-01",
        end="2020-02-01",
        label="close_return",
    )
    assert batch[0].name == "f1"
    assert batch[0].metrics["ic"] == 0.2
