from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from pathlib import Path

SECRET_MARKERS = ("API_KEY", "AUTH_TOKEN", "PASSWORD", "SECRET")


def load_env_file(path: Path, *, environ: MutableMapping[str, str] | None = None) -> None:
    """Load a minimal dotenv file without logging values or overriding existing vars."""
    target = environ if environ is not None else os.environ
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            target.setdefault(key, value)


def redact(value: object, *, environ: Mapping[str, str] | None = None) -> object:
    """Redact known environment secrets from a scalar string."""
    if not isinstance(value, str):
        return value
    result = value
    source = environ if environ is not None else os.environ
    for key, secret in source.items():
        if secret and any(marker in key.upper() for marker in SECRET_MARKERS):
            result = result.replace(secret, "[REDACTED]")
    return result


def sanitized_verifier_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a subprocess environment with all model-provider credentials removed."""
    source = dict(base if base is not None else os.environ)
    for key in list(source):
        upper = key.upper()
        if upper.startswith(("ARK_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_")):
            source.pop(key, None)
        elif any(marker in upper for marker in SECRET_MARKERS):
            source.pop(key, None)
    source["HARNESS_RUNTIME_ROLE"] = "verifier"
    return source


@contextmanager
def temporary_environ(values: Mapping[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
