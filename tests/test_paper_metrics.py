from quant_harness.paper_metrics import (
    best_update_rate,
    fraction_success,
    normalized_ic_gain,
    success_rate,
)


def test_paper_metrics():
    assert normalized_ic_gain(-0.1) == 0
    assert normalized_ic_gain(0.015) == 0.5
    assert normalized_ic_gain(0.03) == 1
    assert normalized_ic_gain(0.3) == 1
    assert success_rate(3, 4) == 0.75
    assert fraction_success([0.01, 0.04, 0.05]) == 2 / 3
    assert best_update_rate([0.01, 0.02, 0.02, 0.03]) == 2 / 3
