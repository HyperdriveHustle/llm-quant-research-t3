from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class ActionValidationError(ValueError):
    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass(frozen=True)
class ResearchAction:
    schema_version: str
    action_id: str
    action: str
    reason: str
    hypothesis_id: str | None
    expected_observation: str | None
    decision_rule: str | None
    arguments: dict[str, Any]
    raw: dict[str, Any]


class ActionParser:
    def __init__(self, schema_path: Path):
        self.schema_path = schema_path
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def parse(self, value: str | dict[str, Any]) -> ResearchAction:
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ActionValidationError(
                    f"action is not valid JSON: {exc.msg}",
                    errors=[{"path": [], "message": exc.msg}],
                ) from exc
        else:
            payload = value
        if not isinstance(payload, dict):
            raise ActionValidationError("action root must be an object")
        errors = sorted(self.validator.iter_errors(payload), key=lambda err: list(err.path))
        if errors:
            details = [
                {
                    "path": [str(part) for part in error.absolute_path],
                    "message": error.message,
                }
                for error in errors
            ]
            raise ActionValidationError(
                "action does not match schema",
                errors=details,
            )
        return ResearchAction(
            schema_version=payload["schema_version"],
            action_id=payload["action_id"],
            action=payload["action"],
            reason=payload["reason"],
            hypothesis_id=payload.get("hypothesis_id"),
            expected_observation=payload.get("expected_observation"),
            decision_rule=payload.get("decision_rule"),
            arguments=dict(payload["arguments"]),
            raw=payload,
        )
