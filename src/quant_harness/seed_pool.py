from __future__ import annotations

import importlib
from typing import Any


class SeedPoolError(RuntimeError):
    pass


def load_alpha158_seeds(search_config: dict[str, Any]) -> list[dict[str, str]]:
    """Load the exact Alpha158 seed subset exposed by the pinned paper runtime."""
    module = importlib.import_module("factors.lib.alpha158")
    _, compiled = module.load_factors_alpha158(
        exclude_var=search_config.get("exclude_variable"),
        collection=search_config["seed_collections"],
    )
    seeds = [
        {
            "name": str(item["name"]),
            "expression": str(item.get("qlib_expression_default") or item.get("qlib_expression")),
        }
        for item in compiled.values()
    ]
    max_seeds = search_config.get("max_seeds")
    if max_seeds is not None:
        seeds = seeds[: int(max_seeds)]
    if not seeds:
        raise SeedPoolError("Alpha158 seed pool is empty")
    return seeds


def as_agentic_seed_records(seeds: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "factor_id": f"seed_{index:03d}",
            "hypothesis_id": "hyp_seed_pool",
            "parent_factor_id": None,
            "name": seed["name"],
            "expression": seed["expression"],
            "direction": 1,
            "rationale": "Reference seed loaded unchanged from Alpha158.",
            "edit_type": "reference",
        }
        for index, seed in enumerate(seeds, start=1)
    ]
