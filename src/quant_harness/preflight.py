from __future__ import annotations

import time
import uuid
from typing import Any

from .artifacts import file_sha256
from .config import HarnessConfig
from .ffo import FFOClient
from .services import FFOService
from .suite import atomic_json_write, utc_now

DEFAULT_PROBES = (
    {"name": "raw_close", "expression": "$close"},
    {"name": "return_5", "expression": "Ref($close, 5) / $close - 1"},
    {"name": "mean_20", "expression": "Mean($close, 20) / $close - 1"},
    {
        "name": "range_position_60",
        "expression": ("(Max($high, 60) - $close) / (Max($high, 60) - Min($low, 60) + 1e-12)"),
    },
    {
        "name": "relative_volume_20",
        "expression": "$volume / (Mean($volume, 20) + 1e-12)",
    },
)


def run_agentic_preflight(config: HarnessConfig) -> dict[str, Any]:
    config.assert_valid(require_paths=True)
    if config.profile != "agentic_goal_loop":
        raise ValueError("agentic preflight requires agentic_goal_loop")
    run_id = f"preflight_{config.path.stem}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    log_dir = config.run_root / "preflight" / run_id / "service_logs"
    validation = config.raw.get("candidate_validation") or {}
    probes = list(validation.get("probes") or DEFAULT_PROBES)
    start, end = config.raw["agentic"]["check_period"]
    rows = []
    with FFOService(config, config.search_endpoint, role="search", log_dir=log_dir):
        client = FFOClient(
            config.search_endpoint.base_url,
            role="search",
            timeout=int(config.model["timeout_seconds"]),
        )
        for probe in probes:
            try:
                result = client.check(
                    str(probe["expression"]),
                    instruments=str(config.raw["data"]["instruments"]),
                    start=str(start),
                    end=str(end),
                )
                rows.append(
                    {
                        "name": str(probe["name"]),
                        "expression": str(probe["expression"]),
                        "success": result.get("success") is True,
                        "result": result,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "name": str(probe["name"]),
                        "expression": str(probe["expression"]),
                        "success": False,
                        "result": {"error": f"{type(exc).__name__}: {exc}"},
                    }
                )
    report = {
        "schema_version": "0.1",
        "status": "ok" if rows and all(row["success"] for row in rows) else "failed",
        "created_at": utc_now(),
        "profile": config.profile,
        "config_path": str(config.path),
        "config_sha256": file_sha256(config.path),
        "candidate_validation": validation,
        "check_period": {"start": str(start), "end": str(end)},
        "probes": rows,
    }
    report_path = config.run_root / "preflight" / f"{config.path.stem}.json"
    atomic_json_write(report_path, report)
    report["report_path"] = str(report_path)
    return report
