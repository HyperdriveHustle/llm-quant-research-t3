from quant_harness.state import ResearchState
from quant_harness.state_projector import ProjectionConfig, StateProjector


def test_projector_is_deterministic_and_hides_unregistered_windows():
    state = ResearchState(
        task_id="task",
        task_manifest_hash="manifest",
        goal="Find momentum factors",
    )
    state.hypotheses["hyp_1"] = {
        "hypothesis_id": "hyp_1",
        "title": "momentum",
        "status": "active",
    }
    state.factors["factor_1"] = {
        "factor_id": "factor_1",
        "hypothesis_id": "hyp_1",
        "name": "Momentum",
        "expression": "$close",
        "status": "evaluated",
        "created_version": 1,
        "metrics_by_window": {"search_full": {"ic": 0.04}},
    }
    projector = StateProjector(
        ProjectionConfig(
            allowed_actions=("propose", "evaluate", "refine", "pivot", "stop"),
            allowed_window_aliases=("search_full",),
            recent_event_window=20,
            max_factor_evaluations=5000,
            plateau_advisory_valid_evaluations=100,
        )
    )
    first = projector.project(state)
    second = projector.project(state)
    assert first == second
    assert first["task"]["goal"] == "Find momentum factors"
    assert first["allowed_window_aliases"] == ["search_full"]
    assert "test" not in str(first).lower()


def test_plateau_is_advisory_and_never_forces_stop():
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    for index in range(101):
        state.experiments[f"exp_{index}"] = {
            "experiment_id": f"exp_{index}",
            "success": True,
            "metrics": {"ic": 0.01 if index == 0 else 0.0},
        }
    projector = StateProjector(
        ProjectionConfig(
            allowed_actions=("stop",),
            allowed_window_aliases=("search_full",),
            recent_event_window=2,
            max_factor_evaluations=5000,
            plateau_advisory_valid_evaluations=100,
        )
    )
    view = projector.project(state)
    assert view["plateau_advisory"]["active"] is True
    assert view["plateau_advisory"]["forces_stop"] is False
