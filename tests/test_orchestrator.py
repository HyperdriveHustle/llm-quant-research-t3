from __future__ import annotations

from types import SimpleNamespace

from quant_harness.artifacts import freeze_submission
from quant_harness.config import load_config
from quant_harness.orchestrator import run_end_to_end


def test_orchestrator_sequences_search_then_verifier(monkeypatch, tmp_path):
    config = load_config("configs/smoke.yaml")
    roles = []

    class DummyService:
        def __init__(self, config, endpoint, *, role, log_dir):
            self.role = role

        def __enter__(self):
            roles.append(f"enter:{self.role}")
            return self

        def __exit__(self, *args):
            roles.append(f"exit:{self.role}")

    class DummyRunner:
        def __init__(self, config, *, search_client, run_id):
            roles.append("runner")

        def run(self):
            return freeze_submission(
                target=tmp_path / "submission.json",
                run_id="run_mock",
                profile="smoke",
                factors=[],
                hashes={},
                search_summary={},
            )

    monkeypatch.setattr("quant_harness.orchestrator.FFOService", DummyService)
    monkeypatch.setattr("quant_harness.orchestrator.PaperRunner", DummyRunner)
    monkeypatch.setattr(
        "quant_harness.orchestrator.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    submission, report = run_end_to_end(config)
    assert roles == [
        "enter:search",
        "runner",
        "exit:search",
        "enter:verifier",
        "exit:verifier",
    ]
    assert submission.name == "submission.json"
    assert report.name == "verifier_report.json"


def test_orchestrator_selects_agentic_runner_only_for_agentic_profile(monkeypatch, tmp_path):
    config = load_config("configs/agentic-smoke.yaml")
    roles = []

    class DummyService:
        def __init__(self, config, endpoint, *, role, log_dir):
            self.role = role

        def __enter__(self):
            roles.append(f"enter:{self.role}")
            return self

        def __exit__(self, *args):
            roles.append(f"exit:{self.role}")

    class DummyRunner:
        def run(self):
            roles.append("agentic-runner")
            return freeze_submission(
                target=tmp_path / "agentic-submission.json",
                run_id="run_agentic_mock",
                profile="agentic_goal_loop",
                factors=[],
                hashes={},
                search_summary={},
                schema_version="0.2",
            )

    monkeypatch.setattr("quant_harness.orchestrator.FFOService", DummyService)
    monkeypatch.setattr(
        "quant_harness.orchestrator.build_agentic_runner",
        lambda *args, **kwargs: DummyRunner(),
    )
    monkeypatch.setattr(
        "quant_harness.orchestrator.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    run_end_to_end(config)

    assert roles == [
        "enter:search",
        "agentic-runner",
        "exit:search",
        "enter:verifier",
        "exit:verifier",
    ]
