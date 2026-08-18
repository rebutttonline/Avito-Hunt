from decimal import Decimal

from avito_hunt.market_lab import run_market_lab


def test_synthetic_market_lab_is_stable() -> None:
    report = run_market_lab()
    assert report.cases == 160
    assert report.classification_accuracy == Decimal("100.0")
    assert report.mean_market_error_percent <= Decimal("0.1")
    assert report.false_positive_rate == Decimal("0.0")
