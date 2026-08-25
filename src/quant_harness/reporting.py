from __future__ import annotations

import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any

from zss import simple_distance

from .paper_metrics import (
    best_update_rate,
    fraction_success,
    normalized_ic_gain,
    success_rate,
)


def _quality_logs(run_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(run_dir.glob("**/logs/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "request_num" in payload:
            rows.append(payload)
    return rows


def _normalize_constants(node) -> None:
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", str(node.label), re.I):
        node.label = "CONST"
    for child in node.get_children():
        _normalize_constants(child)


def structural_diversity(expressions: list[str], parser_cls) -> dict[str, float | int]:
    trees = []
    for expression in expressions:
        try:
            tree = parser_cls().parse(expression)
            _normalize_constants(tree)
            trees.append(tree)
        except Exception:
            continue
    distances = [
        float(
            simple_distance(
                left,
                right,
                get_children=lambda node: node.get_children(),
                get_label=lambda node: node.label,
            )
        )
        for left, right in combinations(trees, 2)
    ]
    max_distance = max(distances, default=0.0)
    mean_distance = sum(distances) / len(distances) if distances else 0.0
    return {
        "valid_tree_count": len(trees),
        "pair_count": len(distances),
        "mean_ast_distance": mean_distance,
        "max_ast_distance": max_distance,
        "normalized_ast_diversity": (mean_distance / max_distance if max_distance > 0 else 0.0),
    }


def build_paper_search_report(
    *,
    algorithm: str,
    raw_result: dict[str, Any],
    final_factors: list[dict[str, Any]],
    run_dir: Path,
    threshold: float,
    parser_cls,
) -> dict[str, Any]:
    logs = _quality_logs(run_dir)
    total_requests = sum(int(row.get("request_num", 0)) for row in logs)
    total_generated = sum(int(row.get("generated_num", 0)) for row in logs)
    total_accepted = sum(int(row.get("accepted_num", 0)) for row in logs)
    final_ics = [float((factor.get("metrics") or {}).get("ic", 0.0)) for factor in final_factors]
    report: dict[str, Any] = {
        "algorithm": algorithm,
        "quality_log_count": len(logs),
        "search_cost_mean_retries": (total_requests / len(logs) if logs else None),
        "total_requests": total_requests,
        "total_generated": total_generated,
        "total_accepted": total_accepted,
        "success_rate": success_rate(total_accepted, total_generated) if total_generated else None,
        "effective_ic_threshold": threshold,
        "effective_factor_fraction": fraction_success(final_ics, threshold),
        "best_ic": max(final_ics, default=0.0),
        "normalized_best_ic_gain": normalized_ic_gain(max(final_ics, default=0.0), threshold),
        "diversity": structural_diversity(
            [factor["expression"] for factor in final_factors], parser_cls
        ),
        "output_correlation_diversity": {
            "status": "not_computed",
            "reason": "paper commit exposes metrics but not reusable factor score matrices",
        },
    }
    if algorithm in {"cot", "tot"}:
        runs = raw_result.get("runs") or []
        improved = []
        for run in runs:
            seed_ic = float((run.get("seed_metrics") or {}).get("ic", 0.0))
            best_ic = float(((run.get("best") or {}).get("metrics") or {}).get("ic", 0.0))
            improved.append(best_ic > seed_ic)
        report["fraction_runs_improved_over_seed"] = (
            sum(improved) / len(improved) if improved else None
        )
    if algorithm == "ea":
        best_by_round = []
        for row in raw_result.get("history") or []:
            candidates = row.get("unique_candidates") or []
            round_best = max(
                (float((factor.get("metrics") or {}).get("ic", -1e9)) for factor in candidates),
                default=-1e9,
            )
            if round_best > -1e9:
                best_by_round.append(round_best)
        report["best_update_rate"] = best_update_rate(best_by_round)
    return report
