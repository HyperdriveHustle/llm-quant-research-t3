from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

from .config import Endpoint, HarnessConfig
from .env import sanitized_verifier_env
from .ffo import FFOClient


class ServiceError(RuntimeError):
    pass


class FFOService:
    def __init__(
        self,
        config: HarnessConfig,
        endpoint: Endpoint,
        *,
        role: str,
        log_dir: Path,
    ):
        self.config = config
        self.endpoint = endpoint
        self.role = role
        self.log_dir = log_dir
        self.process: subprocess.Popen[bytes] | None = None
        self._log_handle: IO[bytes] | None = None

    def start(self, *, wait_seconds: float = 60) -> FFOService:
        if self.process is not None:
            raise ServiceError("service already started")
        cache_path = self._effective_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{self.role}-ffo.log"
        self._log_handle = log_path.open("wb")
        env = sanitized_verifier_env(os.environ) if self.role == "verifier" else dict(os.environ)
        env.update(
            {
                "HARNESS_RUNTIME_ROLE": self.role,
                "PORT": str(self.endpoint.port),
                "HOST": self.endpoint.host,
                "QLIB_PROVIDER_URI": str(self.config.provider_uri),
                "QLIB_DATA_PATH": str(self.config.provider_uri),
                "QLIB_INSTRUMENTS": self.config.raw["data"]["instruments"],
                "QLIB_REGION": "cn",
                "FACTOR_API_CACHE_PATH": str(cache_path),
                "DEFAULT_MARKET": self.config.raw["data"]["market"],
                "DEFAULT_START": self.config.raw["data"]["start"],
                "DEFAULT_END": self.config.raw["data"]["end"],
                "DEFAULT_LABEL": self.config.raw["data"]["label"],
                "PYTHONUNBUFFERED": "1",
            }
        )
        validation = self.config.raw.get("candidate_validation") or {}
        env.update(
            {
                "FACTOR_CHECK_NAN_POLICY": str(validation.get("policy", "strict")),
                "FACTOR_CHECK_MIN_CROSS_SECTION_COVERAGE": str(
                    validation.get("min_cross_section_coverage", 0.90)
                ),
                "FACTOR_CHECK_MIN_VALID_DATE_FRACTION": str(
                    validation.get("min_valid_date_fraction", 0.90)
                ),
                "FACTOR_CHECK_ABSOLUTE_NAN_CAP": str(validation.get("absolute_nan_cap", 0.10)),
            }
        )
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(self.config.upstream_runtime), existing_pythonpath) if part
        )
        self.process = subprocess.Popen(
            [sys.executable, "api/factor_eval_api.py"],
            cwd=self.config.upstream_runtime,
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )
        client = FFOClient(self.endpoint.base_url, role=self.role, timeout=5)
        deadline = time.time() + wait_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise ServiceError(f"{self.role} FFO exited early; inspect {log_path}")
            try:
                client.health()
                return self
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        self.stop()
        raise ServiceError(f"{self.role} FFO did not become healthy: {last_error}")

    def _effective_cache_path(self) -> Path:
        manifest = self.config.project_root / self.config.raw["data"]["snapshot_manifest"]
        if not manifest.exists():
            return self.endpoint.cache_path
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:12]
        path = self.endpoint.cache_path
        return path.with_name(f"{path.stem}-{digest}{path.suffix}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

    def __enter__(self) -> FFOService:
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
