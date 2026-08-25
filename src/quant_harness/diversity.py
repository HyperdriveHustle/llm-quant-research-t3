from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any


def correlation_diversity(feature_frame) -> dict[str, Any]:
    if feature_frame.shape[1] < 2:
        return {
            "status": "insufficient_factors",
            "pair_count": 0,
            "mean_abs_correlation": None,
            "diversity": None,
        }
    correlation = feature_frame.corr()
    values = [
        abs(float(correlation.iloc[i, j]))
        for i, j in combinations(range(correlation.shape[0]), 2)
        if correlation.iloc[i, j] == correlation.iloc[i, j]
    ]
    if not values:
        return {
            "status": "no_valid_pairs",
            "pair_count": 0,
            "mean_abs_correlation": None,
            "diversity": None,
        }
    mean_abs = sum(values) / len(values)
    return {
        "status": "ok",
        "pair_count": len(values),
        "mean_abs_correlation": mean_abs,
        "diversity": 1.0 - mean_abs,
    }


def evaluate_output_diversity(
    *,
    factors: list[dict[str, Any]],
    provider_uri: Path,
    instruments: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    if len(factors) < 2:
        return correlation_diversity(_EmptyFrame())
    import qlib
    from qlib.constant import REG_CN
    from qlib.data.dataset.loader import QlibDataLoader

    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    fields = [factor["expression"] for factor in factors]
    names = [f"factor_{index}" for index in range(len(factors))]
    loader = QlibDataLoader(config={"feature": (fields, names)})
    data = loader.load(
        instruments=instruments,
        start_time=start,
        end_time=end,
    )
    return correlation_diversity(data["feature"])


class _EmptyFrame:
    shape = (0, 0)
