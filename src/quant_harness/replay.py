from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .actions import ActionParser, ActionValidationError
from .config import HarnessConfig
from .env import temporary_environ
from .model import ArkModelClient
from .suite import atomic_json_write, utc_now


def replay_action_logs(
    *,
    config: HarnessConfig,
    call_logs: list[Path],
    max_output_tokens: int,
    output_path: Path,
) -> dict[str, Any]:
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    parser = ActionParser(config.project_root / "schemas" / "agent_action.schema.json")
    client = ArkModelClient.from_env(
        model=config.model["model_id"],
        api_mode=config.model["api_mode"],
        timeout=int(config.model["timeout_seconds"]),
    )
    model_log_dir = output_path.parent / "model_calls"
    rows = []
    with temporary_environ({"HARNESS_MODEL_LOG_DIR": str(model_log_dir)}):
        for call_log_path in call_logs:
            original = json.loads(call_log_path.read_text(encoding="utf-8"))
            started = time.time()
            row = {
                "source_call_log": str(call_log_path),
                "source_response_id": original.get("response_id"),
                "source_input_tokens": original.get("input_tokens"),
                "source_output_tokens": original.get("output_tokens"),
                "source_response_length": len(original.get("response_text") or ""),
                "requested_max_output_tokens": max_output_tokens,
                "state": "running",
            }
            try:
                response = client.generate(
                    system_prompt=str(original["system_prompt"]),
                    prompt=str(original["prompt"]),
                    temperature=float(config.model["temperature"]),
                    json_output=True,
                    max_attempts=1,
                    max_output_tokens=max_output_tokens,
                )
                schema_errors = []
                try:
                    parser.parse(response.text)
                    schema_valid = True
                except ActionValidationError as exc:
                    schema_valid = False
                    schema_errors = exc.errors or [{"message": str(exc)}]
                row.update(
                    {
                        "state": "completed",
                        "response_id": response.response_id,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "response_length": len(response.text),
                        "response_text": response.text,
                        "response_status": response.status,
                        "incomplete_reason": response.incomplete_reason,
                        "output_item_types": list(response.output_item_types),
                        "content_block_types": list(response.content_block_types),
                        "at_requested_limit": response.output_tokens >= max_output_tokens,
                        "schema_valid": schema_valid,
                        "schema_errors": schema_errors,
                    }
                )
            except Exception as exc:
                row.update(
                    {
                        "state": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            row["elapsed_seconds"] = time.time() - started
            rows.append(row)
            atomic_json_write(output_path, _report(max_output_tokens, rows))
    report = _report(max_output_tokens, rows)
    atomic_json_write(output_path, report)
    return report


def _report(max_output_tokens: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "created_at": utc_now(),
        "experiment": "historical_action_replay_with_larger_output_budget",
        "max_output_tokens": max_output_tokens,
        "call_count": len(rows),
        "completed_count": sum(row["state"] == "completed" for row in rows),
        "schema_valid_count": sum(row.get("schema_valid") is True for row in rows),
        "at_requested_limit_count": sum(row.get("at_requested_limit") is True for row in rows),
        "calls": rows,
    }
