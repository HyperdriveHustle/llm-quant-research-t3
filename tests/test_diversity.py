import pandas as pd

from quant_harness.diversity import correlation_diversity


def test_output_correlation_diversity_uses_absolute_correlation():
    frame = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0],
            "b": [-1.0, -2.0, -3.0, -4.0],
            "c": [1.0, -1.0, 1.0, -1.0],
        }
    )
    result = correlation_diversity(frame)
    assert result["status"] == "ok"
    assert result["pair_count"] == 3
    assert 0 <= result["diversity"] <= 1
    assert result["mean_abs_correlation"] >= 1 / 3


def test_output_diversity_requires_two_factors():
    result = correlation_diversity(pd.DataFrame({"a": [1.0]}))
    assert result["status"] == "insufficient_factors"
    assert result["diversity"] is None
