from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    data_root: Path,
    *,
    output_path: Path,
    qlib_version: str,
    upstream_commit: str,
) -> dict:
    files = []
    for path in sorted(item for item in data_root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": str(path.relative_to(data_root)),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    aggregate = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": "0.1",
        "data_root": os.path.relpath(data_root, output_path.parent),
        "qlib_version": qlib_version,
        "upstream_commit": upstream_commit,
        "file_count": len(files),
        "total_bytes": sum(row["size"] for row in files),
        "aggregate_sha256": aggregate,
        "files": files,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
