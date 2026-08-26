from __future__ import annotations

from pathlib import Path

from .actions import ActionParser
from .agent_policy import GLMAgentPolicy
from .agentic_runner import AgenticRunnerConfig, AgenticSearchRunner
from .artifacts import file_sha256
from .config import HarnessConfig
from .ffo import FFOClient
from .model import ArkModelClient
from .paper_runner import paper_import_context, verify_paper_runtime
from .seed_pool import as_agentic_seed_records, load_alpha158_seeds
from .state_projector import ProjectionConfig, StateProjector
from .tool_gateway import ToolGateway


def build_agentic_runner(
    config: HarnessConfig,
    *,
    search_client: FFOClient,
    run_id: str,
) -> AgenticSearchRunner:
    """Compose the agent runtime without passing it any verifier client or result."""
    if config.profile != "agentic_goal_loop":
        raise ValueError("agentic runner requires profile=agentic_goal_loop")
    verify_paper_runtime(config)
    agentic = config.raw["agentic"]
    window_aliases = {
        str(alias): (str(period[0]), str(period[1]))
        for alias, period in agentic["window_aliases"].items()
    }
    with paper_import_context(config.upstream_runtime):
        seeds = as_agentic_seed_records(load_alpha158_seeds(config.search))
    model_client = ArkModelClient.from_env(
        model=config.model["model_id"],
        api_mode=config.model["api_mode"],
        timeout=int(config.model["timeout_seconds"]),
    )
    policy = GLMAgentPolicy(
        model_client,
        temperature=float(config.model["temperature"]),
    )
    safety = agentic["safety"]
    manifest_path = config.project_root / config.raw["data"]["snapshot_manifest"]
    return AgenticSearchRunner(
        config=AgenticRunnerConfig(
            task_id=str(agentic["task_id"]),
            goal=str(agentic["goal"]),
            task_manifest_hash=file_sha256(config.path),
            invalid_action_threshold=int(safety["invalid_action_threshold"]),
            safety_factor_evaluations=int(safety["factor_evaluations"]),
            emergency_model_turns=(
                None
                if safety["emergency_model_turns"] is None
                else int(safety["emergency_model_turns"])
            ),
            checkpoint_evaluations=tuple(int(value) for value in agentic["checkpoints"]),
            max_submissions=int(config.search["max_submissions"]),
        ),
        policy=policy,
        action_parser=ActionParser(action_schema_path(config.project_root)),
        gateway=ToolGateway(
            search_client=search_client,
            market=str(config.raw["data"]["market"]),
            label=str(config.raw["data"]["label"]),
            instruments=str(config.raw["data"]["instruments"]),
            window_aliases=window_aliases,
            check_period=(
                str(agentic["check_period"][0]),
                str(agentic["check_period"][1]),
            ),
            max_candidates_per_action=int(agentic["max_candidates_per_action"]),
            max_submissions=int(config.search["max_submissions"]),
            safety_factor_evaluations=int(safety["factor_evaluations"]),
        ),
        projector=StateProjector(
            ProjectionConfig(
                allowed_actions=tuple(str(value) for value in agentic["allowed_actions"]),
                allowed_window_aliases=tuple(window_aliases),
                recent_event_window=int(agentic["recent_event_window"]),
                max_factor_evaluations=int(safety["factor_evaluations"]),
                plateau_advisory_valid_evaluations=int(
                    agentic["plateau_advisory_valid_evaluations"]
                ),
            )
        ),
        project_root=config.project_root,
        run_root=config.run_root,
        artifact_root=config.artifact_root,
        trajectory_root=config.trajectory_root,
        config_path=config.path,
        data_manifest_path=manifest_path,
        upstream_commit=config.upstream_commit,
        initial_factors=seeds,
        run_id=run_id,
    )


def action_schema_path(project_root: Path) -> Path:
    return project_root / "schemas" / "agent_action.schema.json"
