from __future__ import annotations

import pytest

from quant_harness.runtime_paths import RunDirectoryError, prepare_run_directory


def test_service_log_directory_may_precede_runner(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "service_logs").mkdir(parents=True)

    prepare_run_directory(run_dir)

    assert run_dir.exists()


def test_existing_run_outputs_are_rejected(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final_state.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RunDirectoryError, match="already contains outputs"):
        prepare_run_directory(run_dir)
