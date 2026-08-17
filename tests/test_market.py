from datetime import UTC, datetime
from decimal import Decimal

from avito_hunt.domain import Listing
from avito_hunt.market import estimate_market, is_deal


def listing(price: int) -> Listing:
    return Listing(
        external_id="deal-1",
        title="iPhone 15 Pro 256 GB",
        url="https://example.test/deal-1",
        price=price,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )


def test_detects_discount_against_robust_median() -> None:
    prices = [98000, 99000, 100000, 101000, 102000, 500000]
    estimate = estimate_market(listing(80000), prices, minimum_count=5)
    assert estimate is not None
    assert estimate.market_price == 100000
    assert estimate.discount_percent == Decimal("20.0")
    assert is_deal(estimate, 15)


def test_requires_enough_comparables() -> None:
    assert estimate_market(listing(80000), [99000, 100000], minimum_count=3) is None


def test_rejects_price_above_threshold() -> None:
    estimate = estimate_market(listing(92000), [100000] * 5, minimum_count=5)
    assert estimate is not None
    assert not is_deal(estimate, 15)
