from __future__ import annotations

import json

import pytest

from quant_harness.artifacts import (
    ArtifactError,
    FrozenSubmission,
    freeze_submission,
    harness_source_sha256,
)


def test_submission_hash_detects_tampering(tmp_path):
    path = tmp_path / "submission.json"
    frozen = freeze_submission(
        target=path,
        run_id="run_test",
        profile="smoke",
        factors=[{"name": "f", "expression": "$close", "metrics": {"ic": 0.1}}],
        hashes={"config": "abc"},
        search_summary={"best_ic": 0.1},
    )
    assert FrozenSubmission.load(path).submission_hash == frozen.submission_hash
    path.chmod(0o644)
    payload = json.loads(path.read_text())
    payload["body"]["factors"][0]["expression"] = "$open"
    path.write_text(json.dumps(payload))
    with pytest.raises(ArtifactError, match="hash mismatch"):
        FrozenSubmission.load(path)


def test_harness_source_hash_is_content_sensitive(tmp_path):
    source = tmp_path / "src" / "quant_harness"
    schemas = tmp_path / "schemas"
    source.mkdir(parents=True)
    schemas.mkdir()
    (source / "b.py").write_text("B = 2\n", encoding="utf-8")
    (source / "a.py").write_text("A = 1\n", encoding="utf-8")
    (schemas / "action.json").write_text("{}", encoding="utf-8")
    first = harness_source_sha256(tmp_path)

    (source / "a.py").write_text("A = 3\n", encoding="utf-8")

    assert harness_source_sha256(tmp_path) != first
