from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
import uuid
from pathlib import Path, PurePosixPath


class DataDownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=180) as response, temporary.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    os.replace(temporary, target)


def _download_exact(url: str, target: Path, expected_size: int) -> None:
    """Download with resumable range requests and fail closed on truncation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    if target.exists() and target.stat().st_size != expected_size:
        os.replace(target, partial)
    for _ in range(8):
        current = partial.stat().st_size if partial.exists() else 0
        if current == expected_size:
            os.replace(partial, target)
            return
        if current > expected_size:
            partial.unlink()
            current = 0
        headers = {"Range": f"bytes={current}-"} if current else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=180) as response:
            status = getattr(response, "status", response.getcode())
            append = current > 0 and status == 206
            mode = "ab" if append else "wb"
            with partial.open(mode) as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        size = partial.stat().st_size
        if size == expected_size:
            os.replace(partial, target)
            return
    raise DataDownloadError(
        f"archive download incomplete: got "
        f"{partial.stat().st_size if partial.exists() else 0}, expected {expected_size}"
    )


def _safe_relative(member_name: str, common_root: str) -> Path:
    pure = PurePosixPath(member_name)
    parts = pure.parts
    if not parts or parts[0] != common_root:
        raise DataDownloadError(f"archive member outside common root: {member_name}")
    relative = PurePosixPath(*parts[1:])
    if relative.is_absolute() or ".." in relative.parts:
        raise DataDownloadError(f"unsafe archive member: {member_name}")
    return Path(*relative.parts)


def _extract_archive(archive: Path, target: Path) -> None:
    temporary = target.parent / f".{target.name}.extract-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            roots = {PurePosixPath(member.name).parts[0] for member in members if member.name}
            if len(roots) != 1:
                raise DataDownloadError("archive must have one common top-level directory")
            common_root = next(iter(roots))
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    raise DataDownloadError(f"unsupported archive member: {member.name}")
                relative = _safe_relative(member.name, common_root)
                if not relative.parts:
                    continue
                destination = temporary / relative
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        if target.exists():
            raise DataDownloadError(f"target already exists: {target}")
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def download_release(
    *,
    release_tag: str,
    manifest_url: str,
    archive_url: str,
    target: Path,
) -> dict:
    release_dir = target.parent
    manifest_path = release_dir / "qlib_bin.manifest.json"
    archive_path = release_dir / "qlib_bin.tar.gz"
    if not manifest_path.exists():
        _download(manifest_url, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_tag") != release_tag:
        raise DataDownloadError("manifest release tag mismatch")
    expected_size = int(manifest["archive_size_bytes"])
    if not archive_path.exists() or archive_path.stat().st_size != expected_size:
        _download_exact(archive_url, archive_path, expected_size)
    if archive_path.stat().st_size != expected_size:
        raise DataDownloadError("archive size mismatch")
    expected_hash = str(manifest["archive_sha256"]).removeprefix("sha256:")
    actual_hash = sha256_file(archive_path)
    if actual_hash != expected_hash:
        raise DataDownloadError("archive hash mismatch")
    if not target.exists():
        _extract_archive(archive_path, target)
    return {
        "release_tag": release_tag,
        "archive_sha256": actual_hash,
        "archive_size_bytes": expected_size,
        "target": str(target),
        "source_manifest": manifest,
    }
