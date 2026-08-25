from quant_harness.snapshot import build_manifest


def test_snapshot_manifest_is_path_portable(tmp_path):
    data = tmp_path / "data" / "raw"
    data.mkdir(parents=True)
    (data / "x.bin").write_bytes(b"abc")
    output = tmp_path / "data" / "snapshots" / "manifest.json"
    manifest = build_manifest(
        data,
        output_path=output,
        qlib_version="0.9.7",
        upstream_commit="a" * 40,
    )
    assert not manifest["data_root"].startswith("/")
    assert manifest["file_count"] == 1
