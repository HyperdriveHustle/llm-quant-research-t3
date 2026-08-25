from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class TrajectoryWriter:
    """Append-only JSONL writer. It never accepts credentials."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "schema_version": "0.1",
            "event_id": f"evt_{uuid.uuid4().hex}",
            "timestamp_unix": time.time(),
            "event_type": event_type,
            "runtime_role": os.getenv("HARNESS_RUNTIME_ROLE", "unknown"),
            "payload": payload,
        }
        forbidden = ("api_key", "authorization", "auth_token", "password", "secret")

        def walk_keys(value: Any):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).lower()
                    yield from walk_keys(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from walk_keys(child)

        if any(marker in key for key in walk_keys(event) for marker in forbidden):
            raise ValueError("trajectory payload contains a forbidden secret-like key")
        serialized = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return event


def writer_from_env() -> TrajectoryWriter | None:
    raw = os.getenv("HARNESS_TRAJECTORY_PATH")
    return TrajectoryWriter(Path(raw)) if raw else None
