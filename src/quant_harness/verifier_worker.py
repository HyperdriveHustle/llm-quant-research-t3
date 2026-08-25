from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .artifacts import ArtifactError, FrozenSubmission, file_sha256
from .config import load_config
from .diversity import evaluate_output_diversity
from .ffo import FFOClient
from .isolation import assert_verifier_has_no_model_secret
from .paper_metrics import summarize_factors
from .trajectory import TrajectoryWriter


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
    start, end = config.paper_period
    verified_factors = []
    mismatches = []
    for factor in submission.body["factors"]:
        result = client.evaluate(
            factor["expression"],
            market=config.raw["data"]["market"],
            start=start,
            end=end,
            label=config.raw["data"]["label"],
        )
        claimed = factor.get("metrics") or {}
        verified = result.metrics
        for metric in ("ic", "rank_ic", "icir", "rank_icir"):
            if metric in claimed and metric in verified:
                delta = abs(float(claimed[metric]) - float(verified[metric]))
                if delta > 1e-10:
                    mismatches.append(
                        {
                            "factor": factor.get("name"),
                            "metric": metric,
                            "claimed": claimed[metric],
                            "verified": verified[metric],
                            "absolute_delta": delta,
                        }
                    )
        verified_factors.append(
            {
                "name": factor.get("name"),
                "expression": factor["expression"],
                "success": result.success,
                "metrics": verified,
                "error": result.error,
            }
        )
    threshold = float(config.raw["paper_metrics"]["effective_ic_threshold"])
    report = {
        "schema_version": "0.1",
        "runtime_role": "verifier",
        "run_id": submission.body["run_id"],
        "submission_hash": submission.submission_hash,
        "profile": submission.body["profile"],
        "period": {"start": start, "end": end, "role": "paper_recompute"},
        "factors": verified_factors,
        "paper_summary": summarize_factors(verified_factors, threshold=threshold),
        "metric_mismatches": mismatches,
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
