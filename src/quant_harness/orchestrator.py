from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .agentic_factory import build_agentic_runner
from .config import HarnessConfig
from .env import sanitized_verifier_env
from .ffo import FFOClient
from .isolation import assert_runtime_isolation
from .paper_runner import PaperRunner
from .services import FFOService


class OrchestrationError(RuntimeError):
    pass


def run_end_to_end(config: HarnessConfig) -> tuple[Path, Path]:
    config.assert_valid(require_paths=True)
    assert_runtime_isolation(config)
    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_log_dir = config.run_root / run_id / "service_logs"
    with FFOService(config, config.search_endpoint, role="search", log_dir=run_log_dir):
        search_client = FFOClient(
            config.search_endpoint.base_url,
            role="search",
            timeout=int(config.model["timeout_seconds"]),
        )
        if config.profile == "agentic_goal_loop":
            runner = build_agentic_runner(
                config,
                search_client=search_client,
                run_id=run_id,
            )
        else:
            runner = PaperRunner(config, search_client=search_client, run_id=run_id)
        submission = runner.run()
    report_path = verify_submission(config, submission.path)
    return submission.path, report_path


def verify_submission(config: HarnessConfig, submission_path: Path) -> Path:
    from .artifacts import FrozenSubmission

    submission = FrozenSubmission.load(submission_path)
    report_path = config.artifact_root / submission.body["run_id"] / "verifier_report.json"
    run_log_dir = config.run_root / submission.body["run_id"] / "service_logs"
    with FFOService(config, config.verifier_endpoint, role="verifier", log_dir=run_log_dir):
        env = sanitized_verifier_env(os.environ)
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "quant_harness.verifier_worker",
                "--config",
                str(config.path),
                "--submission",
                str(submission_path),
                "--report",
                str(report_path),
            ],
            cwd=config.project_root,
            env=env,
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            raise OrchestrationError(
                "verifier worker failed; stdout="
                + process.stdout[-2000:]
                + " stderr="
                + process.stderr[-2000:]
            )
    return report_path
