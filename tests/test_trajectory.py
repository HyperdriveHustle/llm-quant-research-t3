from __future__ import annotations

import json

import pytest

from quant_harness.trajectory import TrajectoryWriter


def test_trajectory_is_append_only_and_rejects_secret_keys(tmp_path):
    path = tmp_path / "trajectory.jsonl"
    writer = TrajectoryWriter(path)
    writer.append("run_started", {"run_id": "x"})
    writer.append("run_ended", {"status": "ok"})
    lines = path.read_text().splitlines()
    assert [json.loads(line)["event_type"] for line in lines] == [
        "run_started",
        "run_ended",
    ]
    with pytest.raises(ValueError, match="forbidden"):
        writer.append("bad", {"api_key": "secret"})
