from __future__ import annotations

from itertools import combinations
from typing import Any

from .state import ResearchState


def evaluate_search_objective(
    state: ResearchState,
    objective: dict[str, Any] | None,
) -> dict[str, Any]:
    if not objective:
        return {
            "configured": False,
            "goal_achieved": False,
            "submission_ready_factor_ids": [],
            "factors": [],
            "unmet_requirements": ["no experiment_objective configured"],
        }
    required_windows = list(objective.get("required_search_windows") or [])
    base_min_ic = float(objective.get("min_direction_adjusted_search_ic", 0.0))
    min_ic_by_window = {
        str(alias): float(value)
        for alias, value in (
            objective.get("min_direction_adjusted_search_ic_by_window") or {}
        ).items()
    }
    min_rank_ic = float(objective.get("min_direction_adjusted_search_rank_ic", 0.0))
    require_seed_gain = bool(objective.get("require_beats_best_search_seed", True))
    best_seed_ic = _best_seed_ic(state)
    factor_rows = []
    for factor_id, factor in state.factors.items():
        if factor.get("hypothesis_id") == "hyp_seed_pool":
            continue
        direction = int(factor.get("direction", 1))
        window_rows = {}
        for alias in required_windows:
            experiment = _best_successful_experiment(state, factor_id, alias, direction)
            metrics = {} if experiment is None else experiment.get("metrics") or {}
            signed_ic = direction * float(metrics["ic"]) if "ic" in metrics else None
            signed_rank_ic = direction * float(metrics["rank_ic"]) if "rank_ic" in metrics else None
            minimum_ic = min_ic_by_window.get(alias, base_min_ic)
            window_rows[alias] = {
                "experiment_id": None if experiment is None else experiment["experiment_id"],
                "direction_adjusted_ic": signed_ic,
                "direction_adjusted_rank_ic": signed_rank_ic,
                "minimum_ic": minimum_ic,
                "passes": bool(
                    signed_ic is not None
                    and signed_ic >= minimum_ic
                    and signed_rank_ic is not None
                    and signed_rank_ic > min_rank_ic
                ),
            }
        full_ic = window_rows.get("search_full", {}).get("direction_adjusted_ic")
        beats_seed = bool(
            best_seed_ic is not None and full_ic is not None and full_ic > best_seed_ic
        )
        passes = all(row["passes"] for row in window_rows.values()) and (
            beats_seed or not require_seed_gain
        )
        factor_rows.append(
            {
                "factor_id": factor_id,
                "name": factor.get("name"),
                "hypothesis_id": factor.get("hypothesis_id"),
                "windows": window_rows,
                "beats_best_seed": beats_seed,
                "passes": passes,
            }
        )
    passing = [row for row in factor_rows if row["passes"]]
    min_submissions = int(objective.get("min_submissions", 1))
    min_hypotheses = int(objective.get("min_distinct_hypotheses", 1))
    ready_ids = _ready_factor_ids(passing, min_submissions, min_hypotheses)
    unmet = []
    if not passing:
        unmet.append("no factor passes all required search windows")
    if len(passing) < min_submissions:
        unmet.append(f"passing factor count {len(passing)} is below required {min_submissions}")
    passing_hypotheses = {row["hypothesis_id"] for row in passing}
    if len(passing_hypotheses) < min_hypotheses:
        unmet.append(
            f"passing hypothesis count {len(passing_hypotheses)} is below required {min_hypotheses}"
        )
    return {
        "configured": True,
        "objective_id": objective.get("objective_id"),
        "goal_achieved": bool(ready_ids),
        "required_search_windows": required_windows,
        "best_seed_search_full_ic": best_seed_ic,
        "minimum_submissions": min_submissions,
        "minimum_distinct_hypotheses": min_hypotheses,
        "submission_ready_factor_ids": ready_ids,
        "factors": sorted(
            factor_rows,
            key=lambda row: (
                row["passes"],
                row["windows"].get("search_full", {}).get("direction_adjusted_ic") or float("-inf"),
            ),
            reverse=True,
        )[:20],
        "unmet_requirements": unmet,
    }


def _best_seed_ic(state: ResearchState) -> float | None:
    values = []
    for factor_id, factor in state.factors.items():
        if factor.get("hypothesis_id") != "hyp_seed_pool":
            continue
        direction = int(factor.get("direction", 1))
        experiment = _best_successful_experiment(
            state,
            factor_id,
            "search_full",
            direction,
        )
        if experiment and "ic" in (experiment.get("metrics") or {}):
            values.append(direction * float(experiment["metrics"]["ic"]))
    return max(values, default=None)


def _best_successful_experiment(
    state: ResearchState,
    factor_id: str,
    window_alias: str,
    direction: int,
) -> dict[str, Any] | None:
    rows = [
        experiment
        for experiment in state.experiments.values()
        if experiment["factor_id"] == factor_id
        and experiment["window_alias"] == window_alias
        and experiment.get("success")
        and "ic" in (experiment.get("metrics") or {})
    ]
    return max(
        rows,
        key=lambda row: direction * float(row["metrics"]["ic"]),
        default=None,
    )


def _ready_factor_ids(
    passing: list[dict[str, Any]],
    min_submissions: int,
    min_hypotheses: int,
) -> list[str]:
    if len(passing) < min_submissions:
        return []
    ranked = sorted(
        passing,
        key=lambda row: (
            row["windows"].get("search_full", {}).get("direction_adjusted_ic") or float("-inf")
        ),
        reverse=True,
    )
    for selection in combinations(ranked, min_submissions):
        if len({row["hypothesis_id"] for row in selection}) >= min_hypotheses:
            return [row["factor_id"] for row in selection]
    return []
