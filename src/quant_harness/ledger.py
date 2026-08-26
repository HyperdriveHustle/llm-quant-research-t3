from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import ResearchState, StateReducer, canonical_hash


class LedgerIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    sequence: int
    state_version: int
    event_type: str
    timestamp: float
    previous_hash: str
    payload: dict[str, Any]
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "state_version": self.state_version,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "payload": self.payload,
            "event_hash": self.event_hash,
        }


class ResearchLedger:
    """Hash-chained append-only event ledger with deterministic replay."""

    def __init__(
        self,
        path: Path,
        *,
        task_id: str,
        task_manifest_hash: str,
        goal: str = "",
    ):
        self.path = path
        self.task_id = task_id
        self.task_manifest_hash = task_manifest_hash
        self.goal = goal
        self._lock = threading.Lock()

    def load_events(self) -> list[LedgerEvent]:
        if not self.path.exists():
            return []
        events = []
        previous_hash = "GENESIS"
        expected_sequence = 1
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            if not raw_line:
                continue
            raw = json.loads(raw_line)
            event_hash = raw.pop("event_hash")
            if raw["sequence"] != expected_sequence:
                raise LedgerIntegrityError("ledger sequence is not contiguous")
            if raw["previous_hash"] != previous_hash:
                raise LedgerIntegrityError("ledger previous hash mismatch")
            if canonical_hash(raw) != event_hash:
                raise LedgerIntegrityError("ledger event hash mismatch")
            event = LedgerEvent(event_hash=event_hash, **raw)
            events.append(event)
            previous_hash = event_hash
            expected_sequence += 1
        return events

    def append(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        state: ResearchState,
    ) -> tuple[LedgerEvent, ResearchState]:
        with self._lock:
            events = self.load_events()
            replayed = self.replay(events)
            if replayed.state_hash != state.state_hash:
                raise LedgerIntegrityError("in-memory state differs from ledger replay")
            sequence = len(events) + 1
            next_version = state.state_version + 1
            raw = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "sequence": sequence,
                "state_version": next_version,
                "event_type": event_type,
                "timestamp": time.time(),
                "previous_hash": events[-1].event_hash if events else "GENESIS",
                "payload": payload,
            }
            event_hash = canonical_hash(raw)
            event = LedgerEvent(event_hash=event_hash, **raw)
            updated = StateReducer.apply(
                state,
                event_type,
                payload,
                next_version=next_version,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event, updated

    def replay(self, events: list[LedgerEvent] | None = None) -> ResearchState:
        rows = self.load_events() if events is None else events
        state = ResearchState(
            task_id=self.task_id,
            task_manifest_hash=self.task_manifest_hash,
            goal=self.goal,
        )
        for event in rows:
            state = StateReducer.apply(
                state,
                event.event_type,
                event.payload,
                next_version=event.state_version,
            )
        return state
