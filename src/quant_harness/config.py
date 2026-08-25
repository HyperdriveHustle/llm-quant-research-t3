from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Endpoint:
    role: str
    host: str
    port: int
    cache_path: Path

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class HarnessConfig:
    path: Path
    project_root: Path
    raw: dict[str, Any]
    search_endpoint: Endpoint
    verifier_endpoint: Endpoint

    @property
    def profile(self) -> str:
        return str(self.raw["profile"])

    @property
    def paper_result(self) -> bool:
        return bool(self.raw["paper_result"])

    @property
    def upstream_runtime(self) -> Path:
        return self.project_root / self.raw["upstream"]["paper_runtime"]

    @property
    def upstream_commit(self) -> str:
        return str(self.raw["upstream"]["full_commit_sha"])

    @property
    def provider_uri(self) -> Path:
        return self.project_root / self.raw["data"]["provider_uri"]

    @property
    def paper_period(self) -> tuple[str, str]:
        data = self.raw["data"]
        return str(data["start"]), str(data["end"])

    @property
    def model(self) -> dict[str, Any]:
        return self.raw["model"]

    @property
    def search(self) -> dict[str, Any]:
        return self.raw["search"]

    @property
    def run_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["run_root"]

    @property
    def artifact_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["artifact_root"]

    @property
    def trajectory_root(self) -> Path:
        return self.project_root / self.raw["runtime"]["trajectory_root"]

    def validate(self, *, require_paths: bool = False) -> list[str]:
        errors: list[str] = []
        upstream = self.raw.get("upstream", {})
        if upstream.get("engine") != "qlib" or upstream.get("assay_enabled"):
            errors.append("paper_reproduction requires Qlib and assay_enabled=false")
        if not re.fullmatch(r"[0-9a-f]{40}", self.upstream_commit):
            errors.append("upstream.full_commit_sha must be a full 40-char SHA")
        if self.raw.get("data", {}).get("market") != "csi300":
            errors.append("strict T3 market must be csi300")
        if self.raw.get("data", {}).get("label") != "close_return":
            errors.append("strict T3 label must be close_return")
        if self.search.get("algorithm") not in {"cot", "tot", "ea"}:
            errors.append("search.algorithm must be cot, tot, or ea")
        if self.paper_result and not self.raw.get("exact_paper_snapshot_verified", False):
            errors.append("paper_result=true requires exact_paper_snapshot_verified=true")
        if self.search_endpoint.base_url == self.verifier_endpoint.base_url:
            errors.append("search and verifier endpoints must differ")
        if self.search_endpoint.cache_path == self.verifier_endpoint.cache_path:
            errors.append("search and verifier caches must differ")
        for endpoint in (self.search_endpoint, self.verifier_endpoint):
            if endpoint.host not in {"127.0.0.1", "localhost"}:
                errors.append(f"{endpoint.role} endpoint must bind to loopback")
            try:
                endpoint.cache_path.relative_to(self.project_root)
            except ValueError:
                errors.append(f"{endpoint.role} cache must stay inside project")
        for name, enabled in self.raw.get("extensions", {}).items():
            if (
                self.profile
                in {
                    "paper_reproduction",
                    "paper_compatible_reproduction",
                }
                and enabled
            ):
                errors.append(f"extension {name} must be disabled in paper-compatible profiles")
        model = self.model

        def walk_keys(value: Any):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).lower()
                    yield from walk_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk_keys(child)

        forbidden_config_keys = {"api_key", "authorization", "auth_token", "password", "secret"}
        if any(key in forbidden_config_keys for key in walk_keys(self.raw)):
            errors.append("config must not contain literal credential fields")
        if model.get("provider") != "ark_coding_openai":
            errors.append("model.provider must be ark_coding_openai")
        if model.get("api_mode") not in {"responses", "chat_completions"}:
            errors.append("model.api_mode must be responses or chat_completions")
        for key in ("api_key_env", "base_url_env"):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(model.get(key, ""))):
                errors.append(f"model.{key} must name an environment variable")
        if require_paths:
            if not self.upstream_runtime.exists():
                errors.append(f"missing upstream runtime: {self.upstream_runtime}")
            if not self.provider_uri.exists():
                errors.append(f"missing Qlib data: {self.provider_uri}")
        return errors

    def assert_valid(self, *, require_paths: bool = False) -> None:
        errors = self.validate(require_paths=require_paths)
        if errors:
            raise ConfigError("; ".join(errors))


def _endpoint(project_root: Path, role: str, raw: dict[str, Any]) -> Endpoint:
    return Endpoint(
        role=role,
        host=str(raw["host"]),
        port=int(raw["port"]),
        cache_path=project_root / str(raw["cache_path"]),
    )


def load_config(path: str | Path) -> HarnessConfig:
    config_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    project_root = config_path.parent.parent.resolve()
    required = ("profile", "paper_result", "upstream", "data", "model", "search", "runtime")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ConfigError(f"missing config keys: {', '.join(missing)}")
    runtime = raw["runtime"]
    cfg = HarnessConfig(
        path=config_path,
        project_root=project_root,
        raw=raw,
        search_endpoint=_endpoint(project_root, "search", runtime["search"]),
        verifier_endpoint=_endpoint(project_root, "verifier", runtime["verifier"]),
    )
    cfg.assert_valid(require_paths=False)
    return cfg
