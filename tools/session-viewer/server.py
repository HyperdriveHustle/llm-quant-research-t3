#!/usr/bin/env python3
"""Local, read-only viewer for one quant-agent research trajectory."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SENSITIVE_MARKERS = ("api_key", "authorization", "password", "secret", "auth_token")
MODEL_EVENT_TYPES = {
    "propose",
    "evaluate",
    "refine",
    "pivot",
    "stop",
    "invalid_action",
    "model_output_incomplete",
}


def _safe_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    output = {}
    for key, child in value.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            output[str(key)] = "[REDACTED]"
        else:
            output[str(key)] = _safe_value(child)
    return output


class TaskSessionStore:
    def __init__(self, project_root: Path, run_id: str):
        self.project_root = project_root.expanduser().resolve()
        self.run_id = run_id
        self.ledger_path = (
            self.project_root / "trajectories" / run_id / "agent" / "ledger.jsonl"
        ).resolve()
        self.model_log_dir = (self.project_root / "runs" / run_id / "model_calls").resolve()
        self._assert_inside(self.ledger_path)
        self._assert_inside(self.model_log_dir)
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._model_calls: dict[str, dict[str, Any]] = {}
        self.refresh()

    def _assert_inside(self, path: Path) -> None:
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes project root: {path}") from exc

    def refresh(self) -> None:
        if not self.ledger_path.is_file():
            raise FileNotFoundError(f"Ledger not found: {self.ledger_path}")
        events = []
        for line_no, line in enumerate(
            self.ledger_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid ledger JSON at line {line_no}: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Ledger line {line_no} is not an object")
            events.append(event)
        model_calls = {}
        if self.model_log_dir.is_dir():
            for path in sorted(self.model_log_dir.glob("*.json")):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                response_id = record.get("response_id")
                if response_id:
                    record["_file"] = str(path)
                    model_calls[str(response_id)] = record
        with self._lock:
            self._events = events
            self._model_calls = model_calls

    def index_payload(self) -> dict[str, Any]:
        self.refresh()
        with self._lock:
            events = list(self._events)
        total_calls = 0
        total_tokens = 0
        factor_evaluations = 0
        event_rows = []
        for event in events:
            payload = event.get("payload") or {}
            usage = payload.get("usage") or {}
            total_calls += int(usage.get("model_calls", 0))
            total_tokens += int(usage.get("logical_tokens", 0))
            factor_evaluations += len(payload.get("experiments") or [])
            action = payload.get("model_action") or {}
            observation = payload.get("observation") or {}
            event_rows.append(
                {
                    "sequence": event.get("sequence"),
                    "state_version": event.get("state_version"),
                    "event_type": event.get("event_type"),
                    "timestamp": event.get("timestamp"),
                    "action": action.get("action"),
                    "action_id": payload.get("action_id"),
                    "status": observation.get("status"),
                    "model_calls": int(usage.get("model_calls", 0)),
                    "logical_tokens": int(usage.get("logical_tokens", 0)),
                    "factor_evaluations": len(payload.get("experiments") or []),
                    "response_id": payload.get("response_id"),
                    "has_model_call": bool(
                        payload.get("response_id") in self._model_calls
                    ),
                }
            )
        terminal = next(
            (
                event.get("event_type")
                for event in reversed(events)
                if event.get("event_type") in {"stop", "forced_stop"}
            ),
            None,
        )
        return {
            "run_id": self.run_id,
            "project_root": str(self.project_root),
            "ledger_path": str(self.ledger_path),
            "event_count": len(events),
            "model_calls": total_calls,
            "logical_tokens": total_tokens,
            "factor_evaluations": factor_evaluations,
            "invalid_actions": sum(
                event.get("event_type") == "invalid_action" for event in events
            ),
            "incomplete_outputs": sum(
                event.get("event_type") == "model_output_incomplete" for event in events
            ),
            "terminal_event": terminal,
            "events": event_rows,
        }

    def read_event(self, sequence: int) -> dict[str, Any]:
        self.refresh()
        with self._lock:
            event = next(
                (row for row in self._events if int(row.get("sequence", -1)) == sequence),
                None,
            )
            if event is None:
                raise IndexError(f"Unknown sequence: {sequence}")
            payload = event.get("payload") or {}
            response_id = payload.get("response_id")
            model_call = self._model_calls.get(str(response_id)) if response_id else None
        messages = []
        if model_call:
            messages = [
                {
                    "role": "system",
                    "label": "System instructions",
                    "content": model_call.get("system_prompt"),
                },
                {
                    "role": "user",
                    "label": "Projected ResearchState",
                    "content": model_call.get("prompt"),
                },
                {
                    "role": "assistant",
                    "label": "Model response",
                    "content": model_call.get("response_text"),
                },
            ]
        return _safe_value(
            {
                "run_id": self.run_id,
                "sequence": sequence,
                "event": event,
                "messages": messages,
                "model_call": model_call,
                "model_action": payload.get("model_action"),
                "harness_observation": payload.get("observation"),
                "experiments": payload.get("experiments") or [],
                "factors": payload.get("factors") or [],
                "errors": payload.get("errors") or [],
            }
        )


class ViewerHandler(BaseHTTPRequestHandler):
    store: TaskSessionStore
    static_dir: Path

    def log_message(self, format_string: str, *args: Any) -> None:
        sys.stderr.write(
            f"[{self.log_date_time_string()}] {self.address_string()} "
            + (format_string % args)
            + "\n"
        )

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "run_id": self.store.run_id})
            return
        if parsed.path == "/api/index":
            self._send_json(self.store.index_payload())
            return
        if parsed.path == "/api/event":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                sequence = int(query.get("sequence", [""])[0])
                self._send_json(self.store.read_event(sequence))
            except ValueError:
                self._send_json(
                    {"error": "sequence must be an integer"}, HTTPStatus.BAD_REQUEST
                )
            except IndexError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        self._send_static(parsed.path)

    def _send_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (self.static_dir / relative).resolve()
        try:
            target.relative_to(self.static_dir)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime_type.startswith("text/") or mime_type in {
            "application/javascript",
            "application/json",
        }:
            mime_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def make_handler(
    store: TaskSessionStore, static_dir: Path
) -> type[ViewerHandler]:
    class ConfiguredHandler(ViewerHandler):
        pass

    ConfiguredHandler.store = store
    ConfiguredHandler.static_dir = static_dir.resolve()
    return ConfiguredHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View one quant-agent trajectory")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parents[2])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8876)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = TaskSessionStore(args.project_root, args.run_id)
    static_dir = Path(__file__).resolve().parent / "static"
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, static_dir))
    print(f"Quant Session Viewer: http://{args.host}:{args.port}")
    print(f"Run: {args.run_id} ({store.index_payload()['event_count']} events)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
