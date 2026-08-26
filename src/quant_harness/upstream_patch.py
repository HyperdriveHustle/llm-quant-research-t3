from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class UpstreamPatchError(RuntimeError):
    pass


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise UpstreamPatchError(f"expected upstream text not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_paper_overlay(
    *,
    project_root: Path,
    runtime: Path,
    expected_commit: str,
) -> None:
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=runtime,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if actual != expected_commit:
        raise UpstreamPatchError(f"commit mismatch: {actual} != {expected_commit}")
    overlay = project_root / "patches" / "agent_llm_client.py"
    target = runtime / "agent" / "llm_client.py"
    shutil.copyfile(overlay, target)
    valid = runtime / "agent" / "qlib_contrib" / "qlib_valid.py"
    _replace_once(
        valid,
        "import pandas as pd\nimport threading\n",
        "import pandas as pd\nimport threading\nimport os\n",
    )
    _replace_once(
        valid,
        '    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region="cn")',
        "    provider_uri = os.environ.get(\n"
        '        "QLIB_PROVIDER_URI", os.path.expanduser("~/.qlib/qlib_data/cn_data")\n'
        "    )\n"
        '    qlib.init(provider_uri=provider_uri, region="cn")',
    )
    api = runtime / "api" / "factor_eval_api.py"
    _replace_once(
        api,
        '    port = int(os.environ.get("PORT", "9889"))\n'
        '    debug = os.environ.get("DEBUG", "false").lower() == "true"',
        '    port = int(os.environ.get("PORT", "9889"))\n'
        '    host = os.environ.get("HOST", "127.0.0.1")\n'
        '    debug = os.environ.get("DEBUG", "false").lower() == "true"',
    )
    _replace_once(
        api,
        '    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)',
        "    app.run(host=host, port=port, debug=debug, threaded=True)",
    )
    client = runtime / "api" / "factor_eval_client.py"
    _replace_once(client, "import requests\n", "import requests\nimport os\n")
    _replace_once(
        client,
        'DEFAULT_API_URL = "http://localhost:9889"',
        'DEFAULT_API_URL = os.environ.get("FACTOR_API_URL", "http://localhost:9889")',
    )
    utils = runtime / "api" / "utils.py"
    _replace_once(
        utils,
        "\n\ndef _spawn_and_run(target, args: tuple, timeout: int) -> SubprocessResult:",
        "\n\ndef _subprocess_entry(q: Queue, target, args):\n"
        '    """Top-level process target required by macOS spawn semantics."""\n'
        "    try:\n"
        "        payload = target(*args)\n"
        "        q.put((True, payload, None))\n"
        "    except Exception as e:\n"
        '        q.put((False, f"{type(e).__name__}: {e}", type(e).__name__))\n'
        "\n\ndef _spawn_and_run(target, args: tuple, timeout: int) -> SubprocessResult:",
    )
    old_local = """    def _wrap(q: Queue, target, args):
        try:
            payload = target(*args)
            q.put((True, payload, None))
        except Exception as e:
            # pass back a trimmed error string + type
            q.put((False, f"{type(e).__name__}: {e}", type(e).__name__))

    p = Process(target=_wrap, args=(q, target, args), daemon=True)"""
    _replace_once(
        utils,
        old_local,
        "    p = Process(target=_subprocess_entry, args=(q, target, args), daemon=True)",
    )
    old_nan_gate = """    nan_ratio = float(feat.isna().mean().mean())
    if nan_ratio > 0.01:
        return {
            "success": False,
            "error_message": f"High NaN ratio: {nan_ratio:.2%}",
            "error_type": "HIGH_NAN_RATIO",
        }
    return {"success": True, "nan_ratio": nan_ratio}"""
    new_nan_gate = """    nan_ratio = float(feat.isna().mean().mean())
    nan_policy = os.environ.get("FACTOR_CHECK_NAN_POLICY", "strict")
    if nan_policy == "coverage_aware":
        min_cross_section = float(
            os.environ.get("FACTOR_CHECK_MIN_CROSS_SECTION_COVERAGE", "0.90")
        )
        min_valid_dates = float(
            os.environ.get("FACTOR_CHECK_MIN_VALID_DATE_FRACTION", "0.90")
        )
        absolute_nan_cap = float(
            os.environ.get("FACTOR_CHECK_ABSOLUTE_NAN_CAP", "0.10")
        )
        date_level = "datetime" if "datetime" in feat.index.names else -1
        coverage_by_date = (
            feat.iloc[:, 0].notna().groupby(level=date_level).mean()
        )
        valid_date_fraction = float(
            (coverage_by_date >= min_cross_section).mean()
        )
        minimum_date_coverage = float(coverage_by_date.min())
        if nan_ratio > absolute_nan_cap or valid_date_fraction < min_valid_dates:
            return {
                "success": False,
                "error_message": (
                    f"Insufficient coverage: nan_ratio={nan_ratio:.2%}, "
                    f"valid_date_fraction={valid_date_fraction:.2%}, "
                    f"minimum_date_coverage={minimum_date_coverage:.2%}"
                ),
                "error_type": "INSUFFICIENT_COVERAGE",
                "nan_ratio": nan_ratio,
                "valid_date_fraction": valid_date_fraction,
                "minimum_date_coverage": minimum_date_coverage,
            }
        return {
            "success": True,
            "nan_ratio": nan_ratio,
            "valid_date_fraction": valid_date_fraction,
            "minimum_date_coverage": minimum_date_coverage,
        }
    if nan_ratio > 0.01:
        return {
            "success": False,
            "error_message": f"High NaN ratio: {nan_ratio:.2%}",
            "error_type": "HIGH_NAN_RATIO",
        }
    return {"success": True, "nan_ratio": nan_ratio}"""
    _replace_once(utils, old_nan_gate, new_nan_gate)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (target, valid, api, client))
    if re.search(r'api_key\s*=\s*["\']sk-', combined):
        raise UpstreamPatchError("hard-coded API key remains after overlay")
