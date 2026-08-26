from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from quant_harness.config import HarnessConfig, load_config
from quant_harness.suite import (
    _initial_status,
    atomic_json_write,
    load_suite,
    run_suite_worker,
    start_suite_background,
    suite_run_directory,
)
from quant_harness.suite_analysis import live_run_progress


def test_real_suite_has_three_valid_orthogonal_tasks():
    definition = load_suite("experiments/agentic-real-3/suite.yaml")
    configs = [load_config(task.config_path) for task in definition.tasks]

    assert definition.execution == "parallel"
    assert len(configs) == 3
    assert all(config.profile == "agentic_goal_loop" for config in configs)
    assert all(config.raw["model"]["model_id"] == "glm-5.3" for config in configs)
    assert all(
        config.raw["agentic"]["safety"]["emergency_model_turns"] is None for config in configs
    )
    assert len({config.search_endpoint.port for config in configs}) == 3
    assert len({config.verifier_endpoint.port for config in configs}) == 3
    assert {
        tuple(config.raw["agentic"]["window_aliases"]["search_full"]) for config in configs
    } == {("2020-01-01", "2023-12-31")}
    assert {
        (config.raw["outcome_verification"]["start"], config.raw["outcome_verification"]["end"])
        for config in configs
    } == {("2024-01-01", "2025-12-31")}
    assert all(config.raw["candidate_validation"]["policy"] == "strict" for config in configs)
    assert [config.raw["experiment_objective"]["objective_id"] for config in configs] == [
        "cross-regime-trend-discovery",
        "liquidity-reversal-discovery",
        "diverse-two-factor-pool",
    ]
    assert configs[2].raw["experiment_objective"]["min_submissions"] == 2
    assert configs[2].raw["experiment_objective"]["min_distinct_hypotheses"] == 2


def test_background_launcher_records_pid_and_never_embeds_secrets(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "configs").mkdir()
    suite_dir = tmp_path / "experiments" / "suite"
    suite_dir.mkdir(parents=True)
    tasks = []
    for index in range(3):
        config_path = tmp_path / "configs" / f"task-{index}.yaml"
        config_path.write_text("profile: test\n", encoding="utf-8")
        tasks.append(
            {
                "task_id": f"task-{index}",
                "title": f"Task {index}",
                "capability": "test",
                "config": f"configs/task-{index}.yaml",
            }
        )
    suite_path = suite_dir / "suite.yaml"
    import yaml

    suite_path.write_text(
        yaml.safe_dump(
            {
                "suite_id": "test-suite",
                "execution": "sequential",
                "tasks": tasks,
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr("quant_harness.suite.subprocess.Popen", fake_popen)
    monkeypatch.setattr("quant_harness.suite._git_state", lambda project_root: (None, None))
    monkeypatch.setenv("ARK_API_KEY", "must-not-be-serialized")

    result = start_suite_background(suite_path)

    launcher = json.loads(
        (tmp_path / "runs" / "suites" / result["suite_run_id"] / "launcher.json").read_text()
    )
    status = json.loads(
        (tmp_path / "runs" / "suites" / result["suite_run_id"] / "status.json").read_text()
    )
    assert launcher["worker_pid"] == 4321
    assert status["state"] == "queued"
    assert "must-not-be-serialized" not in json.dumps(launcher)
    assert "must-not-be-serialized" not in json.dumps(status)
    assert captured["kwargs"]["start_new_session"] is True


def test_suite_worker_runs_tasks_sequentially_and_aggregates(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "configs").mkdir()
    suite_dir = tmp_path / "experiments" / "suite"
    suite_dir.mkdir(parents=True)
    tasks = []
    for index in range(3):
        config_path = tmp_path / "configs" / f"task-{index}.yaml"
        config_path.write_text("profile: test\n", encoding="utf-8")
        tasks.append(
            {
                "task_id": f"task-{index}",
                "title": f"Task {index}",
                "capability": "test",
                "config": f"configs/task-{index}.yaml",
            }
        )
    suite_path = suite_dir / "suite.yaml"
    import yaml

    suite_path.write_text(
        yaml.safe_dump({"suite_id": "worker-suite", "execution": "sequential", "tasks": tasks}),
        encoding="utf-8",
    )
    definition = load_suite(suite_path)
    run_dir = suite_run_directory(definition, "suite-run")
    atomic_json_write(run_dir / "status.json", _initial_status(definition, "suite-run"))
    execution_order = []

    def fake_run(config, *, run_id):
        execution_order.append(run_id)
        return tmp_path / f"{run_id}-submission.json", tmp_path / f"{run_id}-report.json"

    def fake_analysis(*, config, run_id, submission_path, verifier_report_path):
        return {
            "task_id": run_id,
            "terminal_status": "no_discovery",
            "trial_counts": {
                "model_calls": 2,
                "logical_tokens": 100,
                "factor_evaluations": 3,
            },
            "model_turns": 2,
            "elapsed_seconds_agent": 5.0,
            "best_direction_adjusted_search_ic": 0.01,
            "objective_assessment": {"discovery_achieved": False},
            "verifier": {"verification_status": "passed"},
        }

    monkeypatch.setattr("quant_harness.suite.load_config", lambda path: object())
    monkeypatch.setattr("quant_harness.suite.run_end_to_end", fake_run)
    monkeypatch.setattr("quant_harness.suite.analyze_agentic_run", fake_analysis)

    status = run_suite_worker(suite_path, "suite-run")

    assert status["state"] == "completed"
    assert [task["state"] for task in status["tasks"]] == ["completed"] * 3
    assert execution_order == [
        "run_suite-run_task-0",
        "run_suite-run_task-1",
        "run_suite-run_task-2",
    ]
    assert status["aggregate"]["total_model_calls"] == 6
    assert status["aggregate"]["total_logical_tokens"] == 300


def test_parallel_suite_spawns_three_isolated_task_processes(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "configs").mkdir()
    suite_dir = tmp_path / "experiments" / "suite"
    suite_dir.mkdir(parents=True)
    tasks = []
    for index in range(3):
        config_path = tmp_path / "configs" / f"task-{index}.yaml"
        config_path.write_text("profile: test\n", encoding="utf-8")
        tasks.append(
            {
                "task_id": f"parallel-{index}",
                "title": f"Task {index}",
                "capability": "test",
                "config": f"configs/task-{index}.yaml",
            }
        )
    suite_path = suite_dir / "suite.yaml"
    import yaml

    suite_path.write_text(
        yaml.safe_dump({"suite_id": "parallel-suite", "execution": "parallel", "tasks": tasks}),
        encoding="utf-8",
    )
    definition = load_suite(suite_path)
    run_dir = suite_run_directory(definition, "parallel-run")
    atomic_json_write(
        run_dir / "status.json",
        _initial_status(definition, "parallel-run"),
    )
    commands = []

    class CompletedProcess:
        returncode = 0

        @staticmethod
        def poll():
            return 0

    def fake_popen(command, **kwargs):
        commands.append(command)
        analysis_path = Path(command[command.index("--analysis") + 1])
        result_path = Path(command[command.index("--result") + 1])
        run_id = command[command.index("--run-id") + 1]
        analysis = {
            "task_id": run_id,
            "terminal_status": "no_discovery",
            "trial_counts": {
                "model_calls": 1,
                "logical_tokens": 10,
                "factor_evaluations": 1,
            },
            "model_turns": 1,
            "elapsed_seconds_agent": 1.0,
            "best_direction_adjusted_search_ic": 0.0,
            "objective_assessment": {"discovery_achieved": False},
            "verifier": {"verification_status": "passed"},
        }
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        result_path.write_text(
            json.dumps(
                {
                    "state": "completed",
                    "finished_at": "now",
                    "duration_seconds": 1.0,
                    "submission_path": "submission.json",
                    "verifier_report_path": "report.json",
                    "analysis_path": str(analysis_path),
                    "error": None,
                }
            ),
            encoding="utf-8",
        )
        return CompletedProcess()

    monkeypatch.setattr("quant_harness.suite.subprocess.Popen", fake_popen)

    status = run_suite_worker(suite_path, "parallel-run")

    assert len(commands) == 3
    assert all("quant_harness.suite_task" in command for command in commands)
    assert [task["state"] for task in status["tasks"]] == ["completed"] * 3
    assert status["aggregate"]["total_model_calls"] == 3


def test_live_progress_reads_model_tokens_evaluations_and_elapsed(tmp_path):
    original = load_config("configs/real-t1-trend.yaml")
    config = HarnessConfig(
        path=original.path,
        project_root=tmp_path,
        raw=deepcopy(original.raw),
        search_endpoint=original.search_endpoint,
        verifier_endpoint=original.verifier_endpoint,
    )
    ledger = tmp_path / "trajectories" / "run_live" / "agent" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    events = [
        {
            "sequence": 1,
            "timestamp": 100.0,
            "event_type": "bootstrap",
            "payload": {},
        },
        {
            "sequence": 2,
            "timestamp": 112.5,
            "event_type": "evaluate",
            "payload": {
                "usage": {"model_calls": 2, "logical_tokens": 50},
                "experiments": [{"experiment_id": "e1"}, {"experiment_id": "e2"}],
            },
        },
    ]
    ledger.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    progress = live_run_progress(config, "run_live")

    assert progress["model_turns"] == 1
    assert progress["model_calls"] == 2
    assert progress["logical_tokens"] == 50
    assert progress["factor_evaluations"] == 2
    assert progress["elapsed_seconds"] == 12.5
