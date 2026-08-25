from __future__ import annotations

import pytest

from quant_harness.env import redact, sanitized_verifier_env, temporary_environ
from quant_harness.isolation import IsolationError, assert_verifier_has_no_model_secret


def test_redaction_and_verifier_sanitization(monkeypatch):
    env = {
        "ARK_API_KEY": "sensitive-value",
        "ARK_MODEL": "glm-5.3",
        "PATH": "/bin",
    }
    assert redact("error sensitive-value", environ=env) == "error [REDACTED]"
    clean = sanitized_verifier_env(env)
    assert "ARK_API_KEY" not in clean
    assert "ARK_MODEL" not in clean
    assert clean["HARNESS_RUNTIME_ROLE"] == "verifier"


def test_verifier_rejects_model_credentials(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "secret")
    with pytest.raises(IsolationError, match="model credentials"):
        assert_verifier_has_no_model_secret()


def test_temporary_environment_is_restored(monkeypatch):
    monkeypatch.setenv("HARNESS_TEST_ENV", "before")
    with temporary_environ({"HARNESS_TEST_ENV": "during", "HARNESS_NEW_ENV": "x"}):
        assert __import__("os").environ["HARNESS_TEST_ENV"] == "during"
    assert __import__("os").environ["HARNESS_TEST_ENV"] == "before"
    assert "HARNESS_NEW_ENV" not in __import__("os").environ
