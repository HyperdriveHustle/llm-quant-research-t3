from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import load_config
from .orchestrator import run_end_to_end
from .suite import atomic_json_write, utc_now
from .suite_analysis import analyze_agentic_run


def run_suite_task(
    *,
    config_path: Path,
    run_id: str,
    analysis_path: Path,
    result_path: Path,
) -> dict:
    started = time.time()
    result = {
        "state": "running",
        "run_id": run_id,
        "started_at": utc_now(),
        "finished_at": None,
        "duration_seconds": None,
        "submission_path": None,
        "verifier_report_path": None,
        "analysis_path": None,
        "error": None,
    }
    atomic_json_write(result_path, result)
    try:
        config = load_config(config_path)
        submission_path, verifier_report_path = run_end_to_end(config, run_id=run_id)
        analysis = analyze_agentic_run(
            config=config,
            run_id=run_id,
            submission_path=submission_path,
            verifier_report_path=verifier_report_path,
        )
        atomic_json_write(analysis_path, analysis)
        result.update(
            {
                "state": "completed",
                "submission_path": str(submission_path),
                "verifier_report_path": str(verifier_report_path),
                "analysis_path": str(analysis_path),
            }
        )
    except Exception as exc:
        result.update(
            {
                "state": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    result["finished_at"] = utc_now()
    result["duration_seconds"] = time.time() - started
    atomic_json_write(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    result = run_suite_task(
        config_path=args.config.resolve(),
        run_id=args.run_id,
        analysis_path=args.analysis.resolve(),
        result_path=args.result.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["state"] == "completed" else 1)


if __name__ == "__main__":
    main()
