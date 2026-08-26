from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .artifacts import ArtifactError, FrozenSubmission, file_sha256, harness_source_sha256
from .config import load_config
from .diversity import evaluate_output_diversity
from .ffo import FFOClient
from .isolation import assert_verifier_has_no_model_secret
from .paper_metrics import summarize_factors
from .protocol_verifier import ProtocolVerifier
from .trajectory import TrajectoryWriter

METRICS = ("ic", "rank_ic", "icir", "rank_icir")


def _metric_mismatches(
    *,
    factor_name: str | None,
    claimed: dict,
    verified: dict,
) -> list[dict]:
    rows = []
    for metric in METRICS:
        if metric not in claimed or metric not in verified:
            continue
        delta = abs(float(claimed[metric]) - float(verified[metric]))
        if delta > 1e-10:
            rows.append(
                {
                    "factor": factor_name,
                    "metric": metric,
                    "claimed": claimed[metric],
                    "verified": verified[metric],
                    "absolute_delta": delta,
                }
            )
    return rows


def _generalization_row(
    *,
    factor_name: str | None,
    search_metrics: dict,
    outcome_metrics: dict,
) -> dict:
    diagnostics = {}
    for metric in ("ic", "rank_ic", "icir", "rank_icir"):
        search_value = search_metrics.get(metric)
        outcome_value = outcome_metrics.get(metric)
        values = {
            "search": search_value,
            "hidden_oos": outcome_value,
            "absolute_decay": None,
            "retention_ratio": None,
            "sign_consistent": None,
        }
        if search_value is not None and outcome_value is not None:
            search_number = float(search_value)
            outcome_number = float(outcome_value)
            values["absolute_decay"] = abs(search_number) - abs(outcome_number)
            values["sign_consistent"] = search_number * outcome_number > 0
            if search_number != 0:
                values["retention_ratio"] = abs(outcome_number) / abs(search_number)
        diagnostics[metric] = values
    return {"factor": factor_name, "metrics": diagnostics}


def verify(
    *,
    config_path: Path,
    submission_path: Path,
    report_path: Path,
) -> dict:
    assert_verifier_has_no_model_secret()
    config = load_config(config_path)
    submission = FrozenSubmission.load(submission_path)
    expected_hashes = submission.body.get("hashes") or {}
    manifest_path = config.project_root / config.raw["data"]["snapshot_manifest"]
    actual_hashes = {
        "config_sha256": file_sha256(config.path),
        "data_manifest_sha256": file_sha256(manifest_path),
        "upstream_commit": config.upstream_commit,
    }
    if "harness_source_sha256" in expected_hashes:
        actual_hashes["harness_source_sha256"] = harness_source_sha256(config.project_root)
    hash_mismatches = {
        key: {"expected": expected_hashes.get(key), "actual": value}
        for key, value in actual_hashes.items()
        if expected_hashes.get(key) != value
    }
    if hash_mismatches:
        raise ArtifactError(
            "verifier input hashes differ from frozen search inputs: "
            + ", ".join(sorted(hash_mismatches))
        )
    client = FFOClient(
        config.verifier_endpoint.base_url,
        role="verifier",
        timeout=int(config.model["timeout_seconds"]),
    )
    client.health()
    is_agentic = submission.body["profile"] == "agentic_goal_loop"
    protocol_report = None
    if is_agentic:
        agentic = config.raw["agentic"]
        protocol_report = ProtocolVerifier(
            trajectory_root=config.trajectory_root,
            allowed_window_aliases=set(agentic["window_aliases"]),
            action_schema_path=config.project_root / "schemas" / "agent_action.schema.json",
        ).verify(submission)
        outcome = config.raw["outcome_verification"]
        start, end = str(outcome["start"]), str(outcome["end"])
        period_role = str(outcome["role"])
    else:
        start, end = config.paper_period
        period_role = "paper_recompute"
    verified_factors = []
    search_recomputations = []
    generalization = []
    mismatches = []
    for factor in submission.body["factors"]:
        if is_agentic:
            evidence = factor["search_evidence"]
            alias = evidence["window_alias"]
            search_start, search_end = config.raw["agentic"]["window_aliases"][alias]
            search_result = client.evaluate(
                factor["expression"],
                market=config.raw["data"]["market"],
                start=str(search_start),
                end=str(search_end),
                label=config.raw["data"]["label"],
            )
            claimed = evidence.get("metrics") or {}
            if evidence.get("success") is not search_result.success:
                mismatches.append(
                    {
                        "factor": factor.get("name"),
                        "metric": "success",
                        "claimed": evidence.get("success"),
                        "verified": search_result.success,
                        "absolute_delta": None,
                    }
                )
            mismatches.extend(
                _metric_mismatches(
                    factor_name=factor.get("name"),
                    claimed=claimed,
                    verified=search_result.metrics,
                )
            )
            search_recomputations.append(
                {
                    "name": factor.get("name"),
                    "expression": factor["expression"],
                    "window_alias": alias,
                    "start": str(search_start),
                    "end": str(search_end),
                    "success": search_result.success,
                    "metrics": search_result.metrics,
                    "error": search_result.error,
                }
            )
        result = client.evaluate(
            factor["expression"],
            market=config.raw["data"]["market"],
            start=start,
            end=end,
            label=config.raw["data"]["label"],
        )
        if not is_agentic:
            mismatches.extend(
                _metric_mismatches(
                    factor_name=factor.get("name"),
                    claimed=factor.get("metrics") or {},
                    verified=result.metrics,
                )
            )
        verified_factors.append(
            {
                "name": factor.get("name"),
                "expression": factor["expression"],
                "direction": factor.get("direction", 1),
                "success": result.success,
                "metrics": result.metrics,
                "error": result.error,
            }
        )
        if is_agentic:
            generalization.append(
                _generalization_row(
                    factor_name=factor.get("name"),
                    search_metrics=factor["search_evidence"].get("metrics") or {},
                    outcome_metrics=result.metrics,
                )
            )
    seed_baseline = None
    if is_agentic and protocol_report is not None:
        reference_factors = protocol_report.pop("reference_factors")
        seed_results = client.evaluate_batch(
            reference_factors,
            market=config.raw["data"]["market"],
            start=start,
            end=end,
            label=config.raw["data"]["label"],
        )
        if len(seed_results) != len(reference_factors):
            raise ArtifactError("Verifier FFO returned an incomplete seed baseline")
        seed_rows = [
            {
                "factor_id": reference["factor_id"],
                "name": reference["name"],
                "expression": reference["expression"],
                "success": result.success,
                "metrics": result.metrics,
                "error": result.error,
            }
            for reference, result in zip(reference_factors, seed_results)
        ]
        successful_seed_ics = [
            float(row["metrics"]["ic"])
            for row in seed_rows
            if row["success"] and "ic" in row["metrics"]
        ]
        best_seed_ic = max(successful_seed_ics, default=None)
        seed_baseline = {
            "factors": seed_rows,
            "best_hidden_oos_ic": best_seed_ic,
            "submitted_ic_delta_vs_best_seed": [
                {
                    "name": row["name"],
                    "delta": (
                        float(row["metrics"]["ic"]) - best_seed_ic
                        if best_seed_ic is not None and "ic" in row["metrics"]
                        else None
                    ),
                }
                for row in verified_factors
            ],
        }
    threshold = float(config.raw["paper_metrics"]["effective_ic_threshold"])
    recomputation_success = all(row["success"] for row in search_recomputations)
    outcome_success = all(row["success"] for row in verified_factors)
    report = {
        "schema_version": "0.2" if is_agentic else "0.1",
        "runtime_role": "verifier",
        "run_id": submission.body["run_id"],
        "submission_hash": submission.submission_hash,
        "profile": submission.body["profile"],
        "period": {"start": start, "end": end, "role": period_role},
        "factors": verified_factors,
        "paper_summary": summarize_factors(verified_factors, threshold=threshold),
        "metric_mismatches": mismatches,
        "verification_status": (
            "passed" if not mismatches and recomputation_success and outcome_success else "failed"
        ),
        "input_hash_checks": {
            "status": "ok",
            "values": actual_hashes,
        },
        "output_correlation_diversity": evaluate_output_diversity(
            factors=verified_factors,
            provider_uri=config.provider_uri,
            instruments=config.raw["data"]["instruments"],
            start=start,
            end=end,
        ),
        "agent_model_credentials_present": False,
    }
    if is_agentic:
        report.update(
            {
                "protocol_verification": protocol_report,
                "search_evidence_recomputation": search_recomputations,
                "hidden_oos_summary": summarize_factors(
                    verified_factors,
                    threshold=threshold,
                ),
                "generalization_diagnostics": generalization,
                "seed_baseline": seed_baseline,
            }
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, report_path)
    trajectory = TrajectoryWriter(
        config.trajectory_root
        / submission.body["run_id"]
        / "verifier"
        / "verifier_trajectory.jsonl"
    )
    trajectory.append(
        "verification_completed",
        {
            "submission_hash": submission.submission_hash,
            "factor_count": len(verified_factors),
            "mismatch_count": len(mismatches),
            "report_path": str(report_path),
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    verify(
        config_path=args.config.resolve(),
        submission_path=args.submission.resolve(),
        report_path=args.report.resolve(),
    )


if __name__ == "__main__":
    main()
