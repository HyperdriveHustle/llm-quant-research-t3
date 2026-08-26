from __future__ import annotations

from copy import deepcopy

from quant_harness.config import Endpoint, HarnessConfig, load_config
from quant_harness.preflight import run_agentic_preflight


def test_agentic_preflight_checks_representative_rolling_factors(monkeypatch, tmp_path):
    original = load_config("configs/real-t1-trend.yaml")
    raw = deepcopy(original.raw)
    (tmp_path / raw["upstream"]["paper_runtime"]).mkdir(parents=True)
    (tmp_path / raw["data"]["provider_uri"]).mkdir(parents=True)
    config = HarnessConfig(
        path=original.path,
        project_root=tmp_path,
        raw=raw,
        search_endpoint=Endpoint(
            role="search",
            host="127.0.0.1",
            port=19901,
            cache_path=tmp_path / "runs" / "search.sqlite",
        ),
        verifier_endpoint=Endpoint(
            role="verifier",
            host="127.0.0.1",
            port=19902,
            cache_path=tmp_path / "runs" / "verifier.sqlite",
        ),
    )

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    checked = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def check(self, expression, **kwargs):
            checked.append(expression)
            return {
                "success": True,
                "nan_ratio": 0.04,
                "valid_date_fraction": 0.98,
                "minimum_date_coverage": 0.91,
            }

    monkeypatch.setattr("quant_harness.preflight.FFOService", FakeService)
    monkeypatch.setattr("quant_harness.preflight.FFOClient", FakeClient)

    report = run_agentic_preflight(config)

    assert report["status"] == "ok"
    assert len(checked) == 5
    assert any("Mean($close, 20)" in expression for expression in checked)
    assert any("Max($high, 60)" in expression for expression in checked)
    assert report["candidate_validation"]["policy"] == "strict"
