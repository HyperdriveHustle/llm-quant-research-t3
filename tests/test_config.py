from __future__ import annotations

from copy import deepcopy

import pytest

from quant_harness.config import ConfigError, Endpoint, HarnessConfig, load_config


def test_smoke_config_is_explicitly_not_a_paper_result():
    config = load_config("configs/smoke.yaml")
    assert config.profile == "smoke"
    assert config.paper_result is False
    assert config.search_endpoint.base_url != config.verifier_endpoint.base_url
    assert config.search_endpoint.cache_path != config.verifier_endpoint.cache_path


def test_paper_config_keeps_extensions_disabled():
    config = load_config("configs/paper-t3.yaml")
    assert config.profile == "paper_compatible_reproduction"
    assert config.paper_result is False
    assert not any(config.raw["extensions"].values())


def test_same_endpoint_is_rejected():
    original = load_config("configs/smoke.yaml")
    bad = HarnessConfig(
        path=original.path,
        project_root=original.project_root,
        raw=deepcopy(original.raw),
        search_endpoint=original.search_endpoint,
        verifier_endpoint=Endpoint(
            role="verifier",
            host=original.search_endpoint.host,
            port=original.search_endpoint.port,
            cache_path=original.verifier_endpoint.cache_path,
        ),
    )
    with pytest.raises(ConfigError, match="endpoints must differ"):
        bad.assert_valid()


def test_literal_secret_field_is_rejected():
    original = load_config("configs/smoke.yaml")
    raw = deepcopy(original.raw)
    raw["model"]["api_key"] = "do-not-store"
    bad = HarnessConfig(
        path=original.path,
        project_root=original.project_root,
        raw=raw,
        search_endpoint=original.search_endpoint,
        verifier_endpoint=original.verifier_endpoint,
    )
    with pytest.raises(ConfigError, match="literal credential"):
        bad.assert_valid()


def test_agentic_config_separates_search_and_hidden_outcome_periods():
    config = load_config("configs/agentic-smoke.yaml")

    assert config.profile == "agentic_goal_loop"
    assert (
        config.raw["agentic"]["window_aliases"]["search_full"][1]
        < config.raw["outcome_verification"]["start"]
    )


def test_agentic_hidden_outcome_overlap_is_rejected():
    original = load_config("configs/agentic-smoke.yaml")
    raw = deepcopy(original.raw)
    raw["outcome_verification"]["start"] = "2023-03-01"
    bad = HarnessConfig(
        path=original.path,
        project_root=original.project_root,
        raw=raw,
        search_endpoint=original.search_endpoint,
        verifier_endpoint=original.verifier_endpoint,
    )

    with pytest.raises(ConfigError, match="must start after every search window"):
        bad.assert_valid()
