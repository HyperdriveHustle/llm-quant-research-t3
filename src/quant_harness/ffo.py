from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


class FFOError(RuntimeError):
    pass


@dataclass(frozen=True)
class FactorResult:
    name: str
    expression: str
    success: bool
    metrics: dict[str, Any]
    error: str | None = None


class FFOClient:
    """Client for the paper-commit Factor Evaluation API."""

    def __init__(self, base_url: str, *, role: str, timeout: int = 180):
        if role not in {"search", "verifier"}:
            raise ValueError("FFO role must be search or verifier")
        self.base_url = base_url.rstrip("/")
        self.role = role
        self.timeout = int(timeout)

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Harness-Role": self.role,
            },
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FFOError(f"{self.role} FFO HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise FFOError(f"{self.role} FFO request failed: {exc}") from exc

    def health(self) -> dict[str, Any]:
        payload = self._request("/health")
        if payload.get("status") != "healthy":
            raise FFOError(f"{self.role} FFO is not healthy")
        return payload

    def check(
        self,
        expression: str,
        *,
        instruments: str,
        start: str,
        end: str,
    ) -> dict[str, Any]:
        return self._request(
            "/check",
            {
                "expression": expression,
                "instruments": instruments,
                "start": start,
                "end": end,
            },
        )

    def evaluate(
        self,
        expression: str,
        *,
        market: str,
        start: str,
        end: str,
        label: str,
    ) -> FactorResult:
        raw = self._request(
            "/eval",
            {
                "expression": expression,
                "market": market,
                "start": start,
                "end": end,
                "label": label,
                "use_cache": True,
            },
        )
        return FactorResult(
            name=str(raw.get("name", "")),
            expression=expression,
            success=bool(raw.get("success")),
            metrics=dict(raw.get("metrics") or {}),
            error=raw.get("error"),
        )

    def evaluate_batch(
        self,
        factors: Iterable[dict[str, str]],
        *,
        market: str,
        start: str,
        end: str,
        label: str,
    ) -> list[FactorResult]:
        items = list(factors)
        raw = self._request(
            "/batch_eval",
            {
                "factors": items,
                "market": market,
                "start": start,
                "end": end,
                "label": label,
            },
        )
        rows = raw.get("results", raw if isinstance(raw, list) else [])
        results: list[FactorResult] = []
        for index, row in enumerate(rows):
            source = items[index] if index < len(items) else {}
            results.append(
                FactorResult(
                    name=str(row.get("name", source.get("name", ""))),
                    expression=str(row.get("expression", source.get("expression", ""))),
                    success=bool(row.get("success")),
                    metrics=dict(row.get("metrics") or {}),
                    error=row.get("error"),
                )
            )
        return results
