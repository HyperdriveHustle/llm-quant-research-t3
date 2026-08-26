from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from quant_harness.actions import ActionParser
from quant_harness.agent_policy import ScriptedPolicy
from quant_harness.agentic_runner import AgenticRunnerConfig, AgenticSearchRunner
from quant_harness.artifacts import ArtifactError, file_sha256
from quant_harness.config import load_config
from quant_harness.ffo import FactorResult
from quant_harness.protocol_verifier import ProtocolVerifier
from quant_harness.state_projector import ProjectionConfig, StateProjector
from quant_harness.suite_analysis import analyze_agentic_run
from quant_harness.tool_gateway import ToolGateway
from quant_harness.verifier_worker import verify


class FakeSearchFFO:
    role = "search"

    def check(self, expression, **kwargs):
        return {"success": True}

    def evaluate(self, expression, **kwargs):
        ic = 0.05 if "10" in expression else 0.04
        return FactorResult(
            name="candidate",
            expression=expression,
            success=True,
            metrics={"ic": ic, "rank_ic": ic - 0.01, "icir": ic * 5},
        )

    def evaluate_batch(self, factors, **kwargs):
        return [self.evaluate(factor["expression"], **kwargs) for factor in factors]


class IDs:
    def __init__(self):
        self.counts = {}

    def __call__(self, prefix):
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{prefix}_{self.counts[prefix]}"


def scripted_actions():
    hypothesis = {
        "title": "medium-term smoothing",
        "mechanism": "a smoothed price level may reduce daily noise",
        "predicted_direction": 1,
        "falsification_rule": "IC is non-positive",
    }
    candidate = {
        "name": "Mean5",
        "expression": "Mean($close, 5) / $close",
        "direction": 1,
        "rationale": "test a short moving average",
    }
    return [
        {
            "schema_version": "0.2",
            "action_id": "action_1",
            "action": "propose",
            "reason": "register a falsifiable branch",
            "expected_observation": "positive IC",
            "decision_rule": "refine if positive",
            "arguments": {"hypothesis": hypothesis, "candidates": [candidate]},
        },
        {
            "schema_version": "0.2",
            "action_id": "action_2",
            "action": "evaluate",
            "reason": "measure the first candidate",
            "hypothesis_id": "hyp_1",
            "expected_observation": "positive IC",
            "decision_rule": "increase the window if positive",
            "arguments": {"factor_ids": ["factor_1"], "window_alias": "search_full"},
        },
        {
            "schema_version": "0.2",
            "action_id": "action_3",
            "action": "refine",
            "reason": "test a less noisy window",
            "hypothesis_id": "hyp_1",
            "expected_observation": "IC above the parent",
            "decision_rule": "submit only after direct evaluation",
            "arguments": {
                "parent_factor_id": "factor_1",
                "edit_type": "parameter",
                "change_summary": "increase lookback from 5 to 10",
                "candidates": [
                    {
                        "name": "Mean10",
                        "expression": "Mean($close, 10) / $close",
                        "direction": 1,
                        "rationale": "reduce noise",
                    }
                ],
            },
        },
        {
            "schema_version": "0.2",
            "action_id": "action_4",
            "action": "evaluate",
            "reason": "measure the refined factor",
            "hypothesis_id": "hyp_1",
            "expected_observation": "IC above 0.04",
            "decision_rule": "submit if successful",
            "arguments": {"factor_ids": ["factor_2"], "window_alias": "search_full"},
        },
        {
            "schema_version": "0.2",
            "action_id": "action_5",
            "action": "stop",
            "reason": "the refined candidate has direct evidence",
            "arguments": {
                "mode": "submit",
                "factor_ids": ["factor_2"],
                "evidence_ids": ["exp_2"],
                "limitations": ["single search period"],
                "conclusion": "submit the refined candidate",
            },
        },
    ]


def build_runner(
    tmp_path: Path,
    *,
    actions=None,
    model_turns=10,
    initial_factors=None,
    registration_stall_actions=10,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("profile: agentic_goal_loop\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    schema_path = Path("schemas/agent_action.schema.json").resolve()
    runner = AgenticSearchRunner(
        config=AgenticRunnerConfig(
            task_id="task_agentic_test",
            goal="discover and evaluate a non-reference factor",
            task_manifest_hash=file_sha256(config_path),
            invalid_action_threshold=3,
            safety_factor_evaluations=5,
            emergency_model_turns=model_turns,
            checkpoint_evaluations=(1, 2, 5),
            max_submissions=1,
            registration_stall_actions=registration_stall_actions,
        ),
        policy=ScriptedPolicy(actions or scripted_actions()),
        action_parser=ActionParser(schema_path),
        gateway=ToolGateway(
            search_client=FakeSearchFFO(),
            market="csi300",
            label="close_return",
            instruments="CSI300",
            window_aliases={"search_full": ("2023-01-01", "2023-03-31")},
            check_period=("2023-01-03", "2023-01-17"),
            max_candidates_per_action=4,
            max_submissions=1,
            safety_factor_evaluations=5,
            id_factory=IDs(),
        ),
        projector=StateProjector(
            ProjectionConfig(
                allowed_actions=("propose", "evaluate", "refine", "pivot", "stop"),
                allowed_window_aliases=("search_full",),
                recent_event_window=20,
                max_factor_evaluations=5,
                plateau_advisory_valid_evaluations=3,
                registration_stall_actions=registration_stall_actions,
            )
        ),
        project_root=tmp_path,
        run_root=tmp_path / "runs",
        artifact_root=tmp_path / "artifacts",
        trajectory_root=tmp_path / "trajectories",
        config_path=config_path,
        data_manifest_path=manifest_path,
        upstream_commit="a" * 40,
        initial_factors=initial_factors,
        run_id="run_agentic_test",
    )
    return runner, schema_path


def test_scripted_agent_completes_replayable_loop(tmp_path):
    runner, schema_path = build_runner(tmp_path)

    submission = runner.run()
    protocol = ProtocolVerifier(
        trajectory_root=tmp_path / "trajectories",
        allowed_window_aliases={"search_full"},
        action_schema_path=schema_path,
    ).verify(submission)

    assert submission.body["search_summary"]["status"] == "submitted"
    assert submission.body["schema_version"] == "0.2"
    assert submission.body["factors"][0]["factor_id"] == "factor_2"
    assert submission.body["factors"][0]["search_evidence"]["experiment_id"] == "exp_2"
    assert protocol["model_action_audit"] == {
        "valid_actions": 5,
        "invalid_turns": 0,
        "incomplete_turns": 0,
    }
    assert protocol["trial_counts"]["factor_evaluations"] == 2
    assert protocol["pre_freeze_ledger_head_hash"] == submission.body["hashes"]["ledger_head_hash"]
    assert [
        row["factor_evaluations"]
        for row in json.loads(
            (tmp_path / "runs" / "run_agentic_test" / "final_state.json").read_text()
        )["checkpoints"]
    ] == [1, 2]


def test_model_turn_ceiling_is_a_forced_stop_not_success(tmp_path):
    actions = scripted_actions()[:2]
    runner, schema_path = build_runner(tmp_path, actions=actions, model_turns=2)

    submission = runner.run()
    protocol = ProtocolVerifier(
        trajectory_root=tmp_path / "trajectories",
        allowed_window_aliases={"search_full"},
        action_schema_path=schema_path,
    ).verify(submission)

    assert submission.body["search_summary"]["status"] == "forced_stop"
    assert submission.body["factors"] == []
    assert protocol["terminal_status"] == "forced_stop"


def test_repeated_empty_candidate_registration_forces_operational_stop(tmp_path):
    actions = scripted_actions()[:1]
    duplicate_one = dict(actions[0])
    duplicate_one["action_id"] = "duplicate_1"
    duplicate_two = dict(actions[0])
    duplicate_two["action_id"] = "duplicate_2"
    runner, schema_path = build_runner(
        tmp_path,
        actions=[actions[0], duplicate_one, duplicate_two],
        registration_stall_actions=2,
    )

    submission = runner.run()
    protocol = ProtocolVerifier(
        trajectory_root=tmp_path / "trajectories",
        allowed_window_aliases={"search_full"},
        action_schema_path=schema_path,
    ).verify(submission)

    assert submission.body["search_summary"]["status"] == "forced_stop"
    assert protocol["trial_counts"]["candidate_registration_failures"] == 2
    assert "registration stall" in submission.body["search_summary"]["conclusion"]


def test_independent_verifier_recomputes_search_and_hidden_oos(monkeypatch, tmp_path):
    project = tmp_path / "project"
    (project / "configs").mkdir(parents=True)
    (project / "schemas").mkdir()
    shutil.copy("schemas/agent_action.schema.json", project / "schemas")
    raw = yaml.safe_load(Path("configs/agentic-smoke.yaml").read_text())
    raw["upstream"]["paper_runtime"] = "third_party/paper"
    raw["data"]["provider_uri"] = "data/cn"
    raw["experiment_objective"] = {
        "objective_id": "test-objective",
        "required_search_windows": ["search_full"],
        "min_direction_adjusted_search_ic": 0.04,
        "min_direction_adjusted_search_rank_ic": 0.0,
        "min_direction_adjusted_hidden_oos_ic": 0.005,
        "min_direction_adjusted_hidden_oos_rank_ic": 0.0,
        "require_beats_best_search_seed": False,
        "min_submissions": 1,
        "min_distinct_hypotheses": 1,
        "max_mean_abs_output_correlation": None,
    }
    config_path = project / "configs" / "agentic.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest_path = project / raw["data"]["snapshot_manifest"]
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    runner, _ = build_runner(project)
    runner.config_path = config_path
    runner.data_manifest_path = manifest_path
    runner.upstream_commit = raw["upstream"]["full_commit_sha"]
    runner.config = AgenticRunnerConfig(
        task_id="task_agentic_test",
        goal="discover and evaluate a non-reference factor",
        task_manifest_hash=file_sha256(config_path),
        invalid_action_threshold=3,
        safety_factor_evaluations=5,
        emergency_model_turns=10,
        checkpoint_evaluations=(1, 2, 5),
        max_submissions=1,
    )
    runner.ledger.task_manifest_hash = runner.config.task_manifest_hash
    submission = runner.run()

    for key in list(__import__("os").environ):
        if key.startswith("ARK_"):
            monkeypatch.delenv(key, raising=False)

    class FakeVerifierFFO:
        def __init__(self, *args, **kwargs):
            pass

        def health(self):
            return {"status": "healthy"}

        def evaluate(self, expression, *, start, **kwargs):
            ic = 0.05 if start == "2023-01-01" else 0.01
            return FactorResult(
                name="Mean10",
                expression=expression,
                success=True,
                metrics={"ic": ic, "rank_ic": ic - 0.01, "icir": ic * 5},
            )

        def evaluate_batch(self, factors, **kwargs):
            return [self.evaluate(row["expression"], **kwargs) for row in factors]

    monkeypatch.setattr("quant_harness.verifier_worker.FFOClient", FakeVerifierFFO)
    monkeypatch.setattr(
        "quant_harness.verifier_worker.evaluate_output_diversity",
        lambda **kwargs: {"status": "not_applicable"},
    )
    report_path = project / "artifacts" / "run_agentic_test" / "verifier_report.json"

    report = verify(
        config_path=config_path,
        submission_path=submission.path,
        report_path=report_path,
    )

    assert report["period"]["role"] == "hidden_oos"
    assert report["protocol_verification"]["status"] == "ok"
    assert report["metric_mismatches"] == []
    assert report["factors"][0]["metrics"]["ic"] == pytest.approx(0.01)
    assert report["generalization_diagnostics"][0]["metrics"]["ic"][
        "retention_ratio"
    ] == pytest.approx(0.2)
    assert report["research_outcome"]["status"] == "not_supported_hidden_oos"
    assert report["research_outcome"]["factors"][0]["supported"] is False

    analysis = analyze_agentic_run(
        config=load_config(config_path),
        run_id="run_agentic_test",
        submission_path=submission.path,
        verifier_report_path=report_path,
    )
    assert analysis["model_turns"] == 5
    assert len(analysis["optimization_timeline"]) == 2
    assert analysis["optimization_timeline"][-1]["best_direction_adjusted_ic"] == pytest.approx(
        0.05
    )
    assert analysis["objective_assessment"]["discovery_achieved"] is True

    (project / "schemas" / "changed-after-freeze.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactError, match="input hashes differ"):
        verify(
            config_path=config_path,
            submission_path=submission.path,
            report_path=report_path,
        )
