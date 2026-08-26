from __future__ import annotations

import subprocess

from quant_harness.config import load_config
from quant_harness.paper_runner import PaperRunner, paper_import_context
from quant_harness.upstream_patch import apply_paper_overlay


def test_paper_runtime_commit_and_overlay():
    config = load_config("configs/smoke.yaml")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=config.upstream_runtime,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert actual == config.upstream_commit
    source = (config.upstream_runtime / "agent" / "llm_client.py").read_text()
    assert "quant_harness.model" in source
    assert 'api_key="sk-' not in source


def test_upstream_overlay_is_idempotent():
    config = load_config("configs/smoke.yaml")
    apply_paper_overlay(
        project_root=config.project_root,
        runtime=config.upstream_runtime,
        expected_commit=config.upstream_commit,
    )
    source = (config.upstream_runtime / "api" / "utils.py").read_text()
    assert 'FACTOR_CHECK_NAN_POLICY", "strict"' in source
    assert "valid_date_fraction" in source


def test_alpha158_seed_subset_is_loaded_without_vwap(tmp_path):
    config = load_config("configs/smoke.yaml")

    class FakeClient:
        role = "search"

    runner = PaperRunner(config, search_client=FakeClient(), run_id="seed_test")
    runner.trajectory_path = tmp_path / "trajectory.jsonl"
    from quant_harness.trajectory import TrajectoryWriter

    runner.trajectory = TrajectoryWriter(runner.trajectory_path)
    with paper_import_context(config.upstream_runtime):
        seeds = runner._load_seeds()
    assert len(seeds) == 1
    assert "$vwap" not in seeds[0]["expression"].lower()
