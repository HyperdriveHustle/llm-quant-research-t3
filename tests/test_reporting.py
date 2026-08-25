from __future__ import annotations

import importlib
import json

from quant_harness.config import load_config
from quant_harness.paper_runner import paper_import_context
from quant_harness.reporting import build_paper_search_report


def test_paper_report_uses_retry_and_improvement_metrics(tmp_path):
    log_dir = tmp_path / "cot" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "quality.json").write_text(
        json.dumps(
            {
                "request_num": 2,
                "generated_num": 2,
                "accepted_num": 1,
            }
        )
    )
    config = load_config("configs/smoke.yaml")
    with paper_import_context(config.upstream_runtime):
        parser_cls = importlib.import_module("agent.qlib_contrib.qlib_expr_parsing").FactorParser
        report = build_paper_search_report(
            algorithm="cot",
            raw_result={
                "runs": [
                    {
                        "seed_metrics": {"ic": 0.01},
                        "best": {"metrics": {"ic": 0.04}},
                    }
                ]
            },
            final_factors=[
                {"expression": "$close", "metrics": {"ic": 0.04}},
                {"expression": "$open", "metrics": {"ic": 0.02}},
            ],
            run_dir=tmp_path,
            threshold=0.03,
            parser_cls=parser_cls,
        )
    assert report["search_cost_mean_retries"] == 2
    assert report["success_rate"] == 0.5
    assert report["fraction_runs_improved_over_seed"] == 1
    assert report["effective_factor_fraction"] == 0.5
    assert report["diversity"]["valid_tree_count"] == 2
