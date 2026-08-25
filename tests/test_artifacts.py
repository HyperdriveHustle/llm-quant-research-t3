from __future__ import annotations

import json

import pytest

from quant_harness.artifacts import ArtifactError, FrozenSubmission, freeze_submission


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
