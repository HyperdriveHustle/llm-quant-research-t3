from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ArtifactError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def harness_source_sha256(project_root: Path) -> str:
    """Hash executable Harness Python and protocol schemas in path-stable order."""
    roots_and_patterns = (
        (project_root / "src" / "quant_harness", "*.py"),
        (project_root / "schemas", "*.json"),
    )
    files = sorted(
        path
        for root, pattern in roots_and_patterns
        if root.exists()
        for path in root.rglob(pattern)
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenSubmission:
    path: Path
    body: dict[str, Any]
    submission_hash: str

    @classmethod
    def load(cls, path: Path) -> FrozenSubmission:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if set(envelope) != {"body", "submission_hash"}:
            raise ArtifactError("invalid submission envelope")
        expected = payload_hash(envelope["body"])
        if expected != envelope["submission_hash"]:
            raise ArtifactError("submission hash mismatch")
        return cls(path=path, body=envelope["body"], submission_hash=expected)


def freeze_submission(
    *,
    target: Path,
    run_id: str,
    profile: str,
    factors: list[dict[str, Any]],
    hashes: dict[str, str],
    search_summary: dict[str, Any],
    schema_version: str = "0.1",
) -> FrozenSubmission:
    body = {
        "schema_version": schema_version,
        "run_id": run_id,
        "profile": profile,
        "factors": factors,
        "hashes": hashes,
        "search_summary": search_summary,
    }
    digest = payload_hash(body)
    envelope = {"body": body, "submission_hash": digest}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    target.chmod(0o444)
    return FrozenSubmission(path=target, body=body, submission_hash=digest)
