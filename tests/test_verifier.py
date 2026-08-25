from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from quant_harness.artifacts import ArtifactError, file_sha256, freeze_submission
from quant_harness.ffo import FactorResult
from quant_harness.verifier_worker import verify


def test_verifier_recomputes_without_model_credentials(monkeypatch, tmp_path):
    for key in list(__import__("os").environ):
        if key.startswith("ARK_"):
            monkeypatch.delenv(key, raising=False)
    project = tmp_path / "project"
    config_dir = project / "configs"
    config_dir.mkdir(parents=True)
    raw = yaml.safe_load(Path("configs/smoke.yaml").read_text())
    raw["upstream"]["paper_runtime"] = "third_party/paper"
    raw["data"]["provider_uri"] = "data/cn"
    raw["runtime"]["artifact_root"] = "artifacts"
    raw["runtime"]["trajectory_root"] = "trajectories"
    config_path = config_dir / "smoke.yaml"
    config_path.write_text(yaml.safe_dump(raw))
    manifest_path = project / raw["data"]["snapshot_manifest"]
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}")
    submission = freeze_submission(
        target=project / "artifacts" / "run_verify" / "submission.json",
        run_id="run_verify",
        profile="smoke",
        factors=[
            {
                "name": "f",
                "expression": "$close",
                "metrics": {"ic": 0.1, "rank_ic": 0.2},
            }
        ],
        hashes={
            "config_sha256": file_sha256(config_path),
            "data_manifest_sha256": file_sha256(manifest_path),
            "upstream_commit": raw["upstream"]["full_commit_sha"],
        },
        search_summary={"best_ic": 0.1},
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def health(self):
            return {"status": "healthy"}

        def evaluate(self, expression, **kwargs):
            return FactorResult(
                name="f",
                expression=expression,
                success=True,
                metrics={"ic": 0.1, "rank_ic": 0.2},
            )

    monkeypatch.setattr("quant_harness.verifier_worker.FFOClient", FakeClient)
    report_path = project / "artifacts" / "run_verify" / "report.json"
    report = verify(
        config_path=config_path,
        submission_path=submission.path,
        report_path=report_path,
    )
    assert report["agent_model_credentials_present"] is False
    assert report["metric_mismatches"] == []
    assert json.loads(report_path.read_text())["runtime_role"] == "verifier"

    manifest_path.write_text('{"changed":true}')
    with pytest.raises(ArtifactError, match="input hashes differ"):
        verify(
            config_path=config_path,
            submission_path=submission.path,
            report_path=report_path,
        )
