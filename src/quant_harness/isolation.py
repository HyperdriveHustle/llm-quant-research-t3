from __future__ import annotations

import os
from pathlib import Path

from .config import HarnessConfig


class IsolationError(RuntimeError):
    pass


def assert_runtime_isolation(config: HarnessConfig) -> None:
    search = config.search_endpoint
    verifier = config.verifier_endpoint
    if search.base_url == verifier.base_url:
        raise IsolationError("Agent and verifier endpoints are identical")
    if search.cache_path.resolve() == verifier.cache_path.resolve():
        raise IsolationError("Agent and verifier share a cache")
    if search.host not in {"127.0.0.1", "localhost"}:
        raise IsolationError("Search FFO must bind to loopback")
    if verifier.host not in {"127.0.0.1", "localhost"}:
        raise IsolationError("Verifier FFO must bind to loopback")


def assert_verifier_has_no_model_secret() -> None:
    forbidden = [
        key
        for key in os.environ
        if key.upper().startswith(("ARK_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_"))
        or any(marker in key.upper() for marker in ("API_KEY", "AUTH_TOKEN", "PASSWORD", "SECRET"))
    ]
    if forbidden:
        raise IsolationError(
            "Verifier environment contains model credentials: " + ", ".join(sorted(forbidden))
        )


def assert_inside(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise IsolationError(f"path escapes project root: {path}") from exc
