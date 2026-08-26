from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path

from .config import load_config
from .data_audit import audit_qlib_data
from .data_download import download_release
from .env import load_env_file
from .isolation import assert_runtime_isolation
from .model import ArkModelClient
from .orchestrator import run_end_to_end, verify_submission
from .preflight import run_agentic_preflight
from .snapshot import build_manifest
from .suite import read_suite_status, start_suite_background
from .upstream_patch import apply_paper_overlay


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_local_env() -> None:
    load_env_file(_project_root() / ".env")


def doctor(config_path: Path, *, require_data: bool) -> int:
    _load_local_env()
    config = load_config(config_path)
    errors = config.validate(require_paths=require_data)
    try:
        assert_runtime_isolation(config)
    except Exception as exc:
        errors.append(str(exc))
    if not os.getenv(config.model["api_key_env"]):
        errors.append(f"missing secret env {config.model['api_key_env']}")
    if not os.getenv(config.model["base_url_env"]):
        errors.append(f"missing base URL env {config.model['base_url_env']}")
    runtime = config.upstream_runtime
    if runtime.exists():
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=runtime,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0 or result.stdout.strip() != config.upstream_commit:
            errors.append("paper runtime commit does not match config")
        llm_client = runtime / "agent" / "llm_client.py"
        if llm_client.exists():
            source = llm_client.read_text(encoding="utf-8")
            if "quant_harness.model" not in source:
                errors.append("paper runtime security/model patch is not applied")
    summary = {
        "status": "ok" if not errors else "failed",
        "profile": config.profile,
        "paper_result": config.paper_result,
        "upstream_commit": config.upstream_commit,
        "data_present": config.provider_uri.exists(),
        "agent_endpoint": config.search_endpoint.base_url,
        "verifier_endpoint": config.verifier_endpoint.base_url,
        "secrets_loaded": bool(os.getenv(config.model["api_key_env"])),
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def model_smoke(config_path: Path) -> int:
    _load_local_env()
    config = load_config(config_path)
    client = ArkModelClient.from_env(
        model=config.model["model_id"],
        api_mode=config.model["api_mode"],
        timeout=int(config.model["timeout_seconds"]),
    )
    response = client.generate(
        system_prompt="Return valid JSON only.",
        prompt=(
            'Return {"name":"CloseOpen","expression":"Div(Sub($close,$open),'
            'Add($open,1e-12))"} and nothing else.'
        ),
        temperature=0.0,
        json_output=True,
    )
    json.loads(response.text)
    print(
        json.dumps(
            {
                "status": "ok",
                "model": config.model["model_id"],
                "api_mode": config.model["api_mode"],
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "response_id": response.response_id,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def download_data(config_path: Path) -> int:
    config = load_config(config_path)
    source = config.raw["data"]["source"]
    if source.get("type") != "investment_data_release":
        raise ValueError("unsupported data source")
    result = download_release(
        release_tag=source["release_tag"],
        manifest_url=source["manifest_url"],
        archive_url=source["archive_url"],
        target=config.provider_uri,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "release_tag": result["release_tag"],
                "archive_sha256": result["archive_sha256"],
                "target": result["target"],
            },
            indent=2,
        )
    )
    return 0


def snapshot_data(config_path: Path) -> int:
    config = load_config(config_path)
    if not config.provider_uri.exists():
        raise FileNotFoundError(config.provider_uri)
    try:
        qlib_version = importlib.metadata.version("pyqlib")
    except importlib.metadata.PackageNotFoundError:
        qlib_version = "unknown"
    output = config.project_root / config.raw["data"]["snapshot_manifest"]
    manifest = build_manifest(
        config.provider_uri,
        output_path=output,
        qlib_version=qlib_version,
        upstream_commit=config.upstream_commit,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "manifest": str(output),
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
                "aggregate_sha256": manifest["aggregate_sha256"],
            },
            indent=2,
        )
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="qharness")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "doctor",
        "patch-upstream",
        "model-smoke",
        "download-data",
        "snapshot-data",
        "audit-data",
        "verify",
        "run",
        "agentic-preflight",
    ):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
        if name == "doctor":
            command.add_argument("--require-data", action="store_true")
        if name == "verify":
            command.add_argument("--submission", required=True, type=Path)
    start_suite = sub.add_parser("start-suite")
    start_suite.add_argument("--suite", required=True, type=Path)
    suite_status = sub.add_parser("suite-status")
    suite_status.add_argument("--suite-run-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "start-suite":
            _load_local_env()
            result = start_suite_background(args.suite.resolve())
            print(json.dumps({"status": "started", **result}, ensure_ascii=False, indent=2))
            code = 0
        elif args.command == "suite-status":
            result = read_suite_status(args.suite_run_dir.resolve())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            code = 0
        elif args.command == "doctor":
            code = doctor(args.config.resolve(), require_data=args.require_data)
        elif args.command == "patch-upstream":
            config = load_config(args.config.resolve())
            apply_paper_overlay(
                project_root=config.project_root,
                runtime=config.upstream_runtime,
                expected_commit=config.upstream_commit,
            )
            print(json.dumps({"status": "ok", "runtime": str(config.upstream_runtime)}))
            code = 0
        elif args.command == "model-smoke":
            code = model_smoke(args.config.resolve())
        elif args.command == "download-data":
            code = download_data(args.config.resolve())
        elif args.command == "snapshot-data":
            code = snapshot_data(args.config.resolve())
        elif args.command == "audit-data":
            config = load_config(args.config.resolve())
            report = audit_qlib_data(
                config.provider_uri,
                required_start=config.raw["data"]["start"],
                required_end=config.raw["data"]["end"],
                instruments_name=config.raw["data"]["market"],
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            code = 0 if report["status"] == "ok" else 1
        elif args.command == "agentic-preflight":
            config = load_config(args.config.resolve())
            report = run_agentic_preflight(config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            code = 0 if report["status"] == "ok" else 1
        elif args.command == "verify":
            config = load_config(args.config.resolve())
            report = verify_submission(config, args.submission.resolve())
            print(json.dumps({"status": "ok", "verifier_report": str(report)}))
            code = 0
        else:
            _load_local_env()
            config = load_config(args.config.resolve())
            submission, report = run_end_to_end(config)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "paper_result": config.paper_result,
                        "submission": str(submission),
                        "verifier_report": str(report),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            code = 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
