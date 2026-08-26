from __future__ import annotations

from pathlib import Path


class RunDirectoryError(RuntimeError):
    pass


def prepare_run_directory(run_dir: Path) -> None:
    """Allow the orchestrator-created service_logs directory, but no run output reuse."""
    run_dir.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(path.name for path in run_dir.iterdir() if path.name != "service_logs")
    if unexpected:
        raise RunDirectoryError(f"run directory already contains outputs: {', '.join(unexpected)}")
