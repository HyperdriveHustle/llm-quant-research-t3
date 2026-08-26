from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .artifacts import file_sha256
from .config import load_config
from .orchestrator import run_end_to_end
from .suite_analysis import analyze_agentic_run, live_run_progress


class SuiteError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def find_project_root(path: Path) -> Path:
    for candidate in path.parents:
        if (candidate / "pyproject.toml").exists() and (candidate / "src").exists():
            return candidate
    raise SuiteError("cannot locate project root from suite path")


@dataclass(frozen=True)
class SuiteTask:
    task_id: str
    title: str
    capability: str
    config_path: Path


@dataclass(frozen=True)
class SuiteDefinition:
    path: Path
    project_root: Path
    suite_id: str
    execution: str
    require_clean_git: bool
    tasks: tuple[SuiteTask, ...]


def load_suite(path: str | Path) -> SuiteDefinition:
    suite_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SuiteError("suite root must be a mapping")
    project_root = find_project_root(suite_path)
    tasks = []
    for item in raw.get("tasks") or []:
        config_path = (project_root / str(item["config"])).resolve()
        try:
            config_path.relative_to(project_root)
        except ValueError as exc:
            raise SuiteError("task config escapes project root") from exc
        tasks.append(
            SuiteTask(
                task_id=str(item["task_id"]),
                title=str(item["title"]),
                capability=str(item["capability"]),
                config_path=config_path,
            )
        )
    if len(tasks) != 3:
        raise SuiteError("real capability suite must define exactly three tasks")
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise SuiteError("suite task IDs must be unique")
    execution = str(raw.get("execution", "sequential"))
    if execution not in {"sequential", "parallel"}:
        raise SuiteError("suite execution must be sequential or parallel")
    return SuiteDefinition(
        path=suite_path,
        project_root=project_root,
        suite_id=str(raw["suite_id"]),
        execution=execution,
        require_clean_git=bool(raw.get("require_clean_git", False)),
        tasks=tuple(tasks),
    )


def suite_run_directory(definition: SuiteDefinition, suite_run_id: str) -> Path:
    return definition.project_root / "runs" / "suites" / suite_run_id


def start_suite_background(suite_path: Path) -> dict[str, Any]:
    definition = load_suite(suite_path)
    revision, dirty = _git_state(definition.project_root)
    if definition.require_clean_git and (revision is None or dirty is not False):
        raise SuiteError("suite requires a clean Git worktree before launch")
    suite_run_id = f"{definition.suite_id}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    run_dir = suite_run_directory(definition, suite_run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    status_path = run_dir / "status.json"
    log_path = run_dir / "suite.log"
    initial_status = _initial_status(definition, suite_run_id)
    atomic_json_write(status_path, initial_status)
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "quant_harness.suite",
                "--suite",
                str(definition.path),
                "--suite-run-id",
                suite_run_id,
            ],
            cwd=definition.project_root,
            env=dict(os.environ),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    launcher = {
        "suite_run_id": suite_run_id,
        "worker_pid": process.pid,
        "started_at": utc_now(),
        "status_path": str(status_path),
        "log_path": str(log_path),
    }
    atomic_json_write(run_dir / "launcher.json", launcher)
    return launcher


def _initial_status(definition: SuiteDefinition, suite_run_id: str) -> dict[str, Any]:
    revision, dirty = _git_state(definition.project_root)
    return {
        "schema_version": "0.1",
        "suite_id": definition.suite_id,
        "suite_run_id": suite_run_id,
        "suite_path": str(definition.path),
        "suite_sha256": file_sha256(definition.path),
        "git_revision": revision,
        "git_dirty_at_launch": dirty,
        "state": "queued",
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "worker_pid": None,
        "current_task_id": None,
        "current_task_ids": [],
        "tasks": [
            {
                "task_id": task.task_id,
                "title": task.title,
                "capability": task.capability,
                "config_path": str(task.config_path),
                "state": "pending",
                "run_id": None,
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "submission_path": None,
                "verifier_report_path": None,
                "analysis_path": None,
                "task_log_path": None,
                "error": None,
            }
            for task in definition.tasks
        ],
        "aggregate": None,
    }


def _git_state(project_root: Path) -> tuple[str | None, bool | None]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    if revision.returncode != 0:
        return None, None
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    return revision.stdout.strip(), None if status.returncode != 0 else bool(status.stdout.strip())


def run_suite_worker(suite_path: Path, suite_run_id: str) -> dict[str, Any]:
    definition = load_suite(suite_path)
    run_dir = suite_run_directory(definition, suite_run_id)
    status_path = run_dir / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        {
            "state": "running",
            "started_at": utc_now(),
            "worker_pid": os.getpid(),
        }
    )
    atomic_json_write(status_path, status)
    if definition.execution == "parallel":
        analyses = _run_tasks_parallel(definition, suite_run_id, run_dir, status, status_path)
    else:
        analyses = _run_tasks_sequential(definition, suite_run_id, run_dir, status, status_path)
    status["current_task_id"] = None
    status["current_task_ids"] = []
    status["finished_at"] = utc_now()
    status["state"] = (
        "completed"
        if all(task["state"] == "completed" for task in status["tasks"])
        else "completed_with_errors"
    )
    status["aggregate"] = _aggregate_analyses(analyses)
    atomic_json_write(run_dir / "suite-summary.json", status["aggregate"])
    atomic_json_write(status_path, status)
    return status


def _run_tasks_sequential(
    definition: SuiteDefinition,
    suite_run_id: str,
    run_dir: Path,
    status: dict[str, Any],
    status_path: Path,
) -> list[dict[str, Any]]:
    analyses = []
    for index, task in enumerate(definition.tasks):
        task_status = status["tasks"][index]
        run_id = f"run_{suite_run_id}_{task.task_id}"
        started = time.time()
        task_status.update(
            {
                "state": "running",
                "run_id": run_id,
                "started_at": utc_now(),
            }
        )
        status["current_task_id"] = task.task_id
        status["current_task_ids"] = [task.task_id]
        atomic_json_write(status_path, status)
        try:
            config = load_config(task.config_path)
            submission_path, verifier_report_path = run_end_to_end(
                config,
                run_id=run_id,
            )
            analysis = analyze_agentic_run(
                config=config,
                run_id=run_id,
                submission_path=submission_path,
                verifier_report_path=verifier_report_path,
            )
            analysis_path = run_dir / f"{task.task_id}-analysis.json"
            atomic_json_write(analysis_path, analysis)
            analyses.append(analysis)
            task_status.update(
                {
                    "state": "completed",
                    "submission_path": str(submission_path),
                    "verifier_report_path": str(verifier_report_path),
                    "analysis_path": str(analysis_path),
                }
            )
        except Exception as exc:
            task_status.update(
                {
                    "state": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            task_status["finished_at"] = utc_now()
            task_status["duration_seconds"] = time.time() - started
            atomic_json_write(status_path, status)
    return analyses


def _run_tasks_parallel(
    definition: SuiteDefinition,
    suite_run_id: str,
    run_dir: Path,
    status: dict[str, Any],
    status_path: Path,
) -> list[dict[str, Any]]:
    analyses = []
    processes: dict[int, dict[str, Any]] = {}
    status["current_task_id"] = None
    status["current_task_ids"] = [task.task_id for task in definition.tasks]
    for index, task in enumerate(definition.tasks):
        task_status = status["tasks"][index]
        run_id = f"run_{suite_run_id}_{task.task_id}"
        analysis_path = run_dir / f"{task.task_id}-analysis.json"
        result_path = run_dir / f"{task.task_id}-result.json"
        log_path = run_dir / f"{task.task_id}.log"
        task_status.update(
            {
                "state": "running",
                "run_id": run_id,
                "started_at": utc_now(),
                "task_log_path": str(log_path),
            }
        )
        started = time.time()
        log_handle = None
        try:
            log_handle = log_path.open("ab")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "quant_harness.suite_task",
                    "--config",
                    str(task.config_path),
                    "--run-id",
                    run_id,
                    "--analysis",
                    str(analysis_path),
                    "--result",
                    str(result_path),
                ],
                cwd=definition.project_root,
                env=dict(os.environ),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            processes[index] = {
                "process": process,
                "log_handle": log_handle,
                "result_path": result_path,
                "analysis_path": analysis_path,
                "started": started,
            }
        except Exception as exc:
            if log_handle is not None:
                log_handle.close()
            task_status.update(
                {
                    "state": "failed",
                    "finished_at": utc_now(),
                    "duration_seconds": time.time() - started,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    status["current_task_ids"] = [
        task["task_id"] for task in status["tasks"] if task["state"] == "running"
    ]
    atomic_json_write(status_path, status)
    while processes:
        for index, runtime in list(processes.items()):
            process = runtime["process"]
            if process.poll() is None:
                continue
            runtime["log_handle"].close()
            task_status = status["tasks"][index]
            result_path = runtime["result_path"]
            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                task_status.update(
                    {
                        key: result.get(key)
                        for key in (
                            "state",
                            "finished_at",
                            "duration_seconds",
                            "submission_path",
                            "verifier_report_path",
                            "analysis_path",
                            "error",
                        )
                    }
                )
            else:
                task_status.update(
                    {
                        "state": "failed",
                        "finished_at": utc_now(),
                        "duration_seconds": time.time() - runtime["started"],
                        "error": f"task process exited {process.returncode} without result",
                    }
                )
            if task_status["state"] == "completed" and runtime["analysis_path"].exists():
                analyses.append(json.loads(runtime["analysis_path"].read_text(encoding="utf-8")))
            status["current_task_ids"] = [
                task["task_id"] for task in status["tasks"] if task["state"] == "running"
            ]
            del processes[index]
            atomic_json_write(status_path, status)
        if processes:
            time.sleep(2)
    return analyses


def _aggregate_analyses(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    analyses = sorted(analyses, key=lambda analysis: analysis["task_id"])
    return {
        "completed_task_count": len(analyses),
        "discovery_achieved_count": sum(
            analysis["objective_assessment"]["discovery_achieved"] for analysis in analyses
        ),
        "total_model_calls": sum(analysis["trial_counts"]["model_calls"] for analysis in analyses),
        "total_logical_tokens": sum(
            analysis["trial_counts"]["logical_tokens"] for analysis in analyses
        ),
        "total_factor_evaluations": sum(
            analysis["trial_counts"]["factor_evaluations"] for analysis in analyses
        ),
        "total_agent_elapsed_seconds": sum(
            analysis["elapsed_seconds_agent"] for analysis in analyses
        ),
        "tasks": [
            {
                "task_id": analysis["task_id"],
                "terminal_status": analysis["terminal_status"],
                "trial_counts": analysis["trial_counts"],
                "model_turns": analysis["model_turns"],
                "best_direction_adjusted_search_ic": analysis["best_direction_adjusted_search_ic"],
                "objective_assessment": analysis["objective_assessment"],
                "verifier": analysis["verifier"],
            }
            for analysis in analyses
        ],
    }


def read_suite_status(suite_run_dir: Path) -> dict[str, Any]:
    run_dir = suite_run_dir.expanduser().resolve()
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    worker_pid = status.get("worker_pid")
    if worker_pid is None and (run_dir / "launcher.json").exists():
        worker_pid = json.loads((run_dir / "launcher.json").read_text(encoding="utf-8")).get(
            "worker_pid"
        )
    status["worker_alive"] = _pid_alive(worker_pid)
    current_task_ids = status.get("current_task_ids") or []
    if not current_task_ids and status.get("current_task_id"):
        current_task_ids = [status["current_task_id"]]
    if current_task_ids:
        progress = []
        for task_id in current_task_ids:
            task = next(row for row in status["tasks"] if row["task_id"] == task_id)
            config = load_config(Path(task["config_path"]))
            progress.append(live_run_progress(config, task["run_id"]))
        status["live_progress"] = progress[0] if len(progress) == 1 else progress
    else:
        status["live_progress"] = None
    return status


def _pid_alive(pid: int | None) -> bool | None:
    if pid is None:
        return None
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--suite-run-id", required=True)
    args = parser.parse_args()
    status = run_suite_worker(args.suite.resolve(), args.suite_run_id)
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
