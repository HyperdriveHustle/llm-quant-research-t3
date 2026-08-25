from __future__ import annotations

import hashlib
import io
import json
import tarfile

from quant_harness.data_audit import audit_qlib_data
from quant_harness.data_download import download_release


def test_release_download_verifies_and_extracts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    archive = source / "qlib_bin.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"2020-01-01\n2025-12-31\n"
        info = tarfile.TarInfo("qlib_bin/calendars/day.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = source / "qlib_bin.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "release_tag": "test-release",
                "archive_size_bytes": archive.stat().st_size,
                "archive_sha256": f"sha256:{digest}",
            }
        )
    )
    target = tmp_path / "release" / "cn_data"
    result = download_release(
        release_tag="test-release",
        manifest_url=manifest.as_uri(),
        archive_url=archive.as_uri(),
        target=target,
    )
    assert result["archive_sha256"] == digest
    assert (target / "calendars" / "day.txt").exists()


def test_data_audit_detects_coverage_and_membership(tmp_path):
    provider = tmp_path / "cn_data"
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir()
    (provider / "features" / "sh600000").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("2020-01-02\n2025-12-31\n")
    (provider / "instruments" / "csi300.txt").write_text(
        "SH600000\t2020-01-01\t2022-01-01\nSH600000\t2022-01-02\t2025-12-31\n"
    )
    for field in ("open", "high", "low", "close", "volume"):
        (provider / "features" / "sh600000" / f"{field}.day.bin").write_bytes(b"x")
    result = audit_qlib_data(
        provider,
        required_start="2020-01-01",
        required_end="2025-12-31",
    )
    assert result["status"] == "failed"
    assert "calendar does not cover required paper period" in result["findings"]
