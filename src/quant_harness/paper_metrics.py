from __future__ import annotations

from collections.abc import Iterable


def normalized_ic_gain(ic: float, threshold: float = 0.03) -> float:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    return min(max(float(ic) / threshold, 0.0), 1.0)


def success_rate(valid: int, total: int) -> float:
    if total < 0 or valid < 0 or valid > total:
        raise ValueError("invalid candidate counts")
    return 0.0 if total == 0 else valid / total


def fraction_success(ics: Iterable[float], threshold: float = 0.03) -> float:
    values = [float(value) for value in ics]
    return 0.0 if not values else sum(value > threshold for value in values) / len(values)


def best_update_rate(best_ics: Iterable[float]) -> float:
    values = [float(value) for value in best_ics]
    if len(values) <= 1:
        return 0.0
    updates = sum(curr > prev for prev, curr in zip(values, values[1:]))
    return updates / (len(values) - 1)


def summarize_factors(factors: list[dict], *, threshold: float = 0.03) -> dict[str, float | int]:
    ics = [float((factor.get("metrics") or {}).get("ic", 0.0)) for factor in factors]
    best = max(ics, default=0.0)
    return {
        "factor_count": len(factors),
        "best_ic": best,
        "effective_factor_count": sum(ic > threshold for ic in ics),
        "normalized_best_ic_gain": normalized_ic_gain(best, threshold),
    }
