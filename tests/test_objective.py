from __future__ import annotations

from quant_harness.objective import evaluate_search_objective
from quant_harness.state import ResearchState


def test_search_objective_requires_all_windows_seed_gain_and_distinct_hypotheses():
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    state.factors = {
        "seed_1": {
            "factor_id": "seed_1",
            "hypothesis_id": "hyp_seed_pool",
            "direction": 1,
        },
        "factor_1": {
            "factor_id": "factor_1",
            "hypothesis_id": "hyp_1",
            "name": "first",
            "direction": 1,
        },
        "factor_2": {
            "factor_id": "factor_2",
            "hypothesis_id": "hyp_2",
            "name": "second",
            "direction": 1,
        },
    }
    experiments = []
    for factor_id, ic in (("seed_1", 0.01), ("factor_1", 0.03), ("factor_2", 0.025)):
        windows = (
            ("search_full",)
            if factor_id == "seed_1"
            else (
                "search_early",
                "search_late",
                "search_full",
            )
        )
        for alias in windows:
            experiments.append(
                {
                    "experiment_id": f"{factor_id}_{alias}",
                    "factor_id": factor_id,
                    "window_alias": alias,
                    "success": True,
                    "metrics": {"ic": ic, "rank_ic": 0.02},
                }
            )
    state.experiments = {row["experiment_id"]: row for row in experiments}
    objective = {
        "objective_id": "two-factor-test",
        "required_search_windows": ["search_early", "search_late", "search_full"],
        "min_direction_adjusted_search_ic": 0.02,
        "min_direction_adjusted_search_rank_ic": 0.0,
        "require_beats_best_search_seed": True,
        "min_submissions": 2,
        "min_distinct_hypotheses": 2,
    }

    progress = evaluate_search_objective(state, objective)

    assert progress["goal_achieved"] is True
    assert set(progress["submission_ready_factor_ids"]) == {"factor_1", "factor_2"}
    assert progress["best_seed_search_full_ic"] == 0.01


def test_search_objective_reports_missing_window():
    state = ResearchState(task_id="task", task_manifest_hash="manifest")
    state.factors["factor_1"] = {
        "factor_id": "factor_1",
        "hypothesis_id": "hyp_1",
        "name": "factor",
        "direction": 1,
    }
    state.experiments["exp_1"] = {
        "experiment_id": "exp_1",
        "factor_id": "factor_1",
        "window_alias": "search_full",
        "success": True,
        "metrics": {"ic": 0.04, "rank_ic": 0.03},
    }

    progress = evaluate_search_objective(
        state,
        {
            "required_search_windows": ["search_full", "search_late"],
            "min_direction_adjusted_search_ic": 0.01,
            "min_direction_adjusted_search_rank_ic": 0.0,
            "require_beats_best_search_seed": False,
            "min_submissions": 1,
            "min_distinct_hypotheses": 1,
        },
    )

    assert progress["goal_achieved"] is False
    assert progress["factors"][0]["windows"]["search_late"]["passes"] is False
