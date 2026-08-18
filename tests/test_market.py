from datetime import UTC, datetime
from decimal import Decimal

from avito_hunt.domain import ComparableCohorts, Listing, PriceLevel
from avito_hunt.market import estimate_market, estimate_market_hierarchical, is_deal, price_level


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


def test_classifies_all_price_levels() -> None:
    prices = [100000] * 10
    cases = {
        90000: PriceLevel.NORMAL,
        80000: PriceLevel.DEAL,
        70000: PriceLevel.GREAT_DEAL,
        60000: PriceLevel.SUSPICIOUSLY_CHEAP,
    }
    for candidate_price, expected in cases.items():
        estimate = estimate_market(listing(candidate_price), prices, minimum_count=10)
        assert estimate
        assert price_level(estimate) is expected


def test_hierarchical_market_uses_narrowest_sufficient_scope() -> None:
    cohorts = ComparableCohorts(
        exact_region=(100000, 101000),
        nearby_regions=tuple([100000] * 10),
        national=tuple([110000] * 20),
    )
    estimate = estimate_market_hierarchical(listing(80000), cohorts, minimum_count=5)
    assert estimate is not None
    assert estimate.market_scope == "nearby_regions"
    assert estimate.market_price == 100000
    assert estimate.confidence == "medium"
    assert estimate.range_low == 100000
    assert estimate.cheaper_than_percent == 100
