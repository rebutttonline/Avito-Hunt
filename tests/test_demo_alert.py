from avito_hunt.demo_alert import build_demo_listings
from avito_hunt.market import estimate_market, is_deal


def test_demo_feed_produces_one_discounted_listing() -> None:
    listings = build_demo_listings("test")
    assert len(listings) == 11
    deal = listings[-1]
    estimate = estimate_market(
        deal,
        [listing.price for listing in listings[:-1]],
        minimum_count=10,
    )
    assert estimate is not None
    assert estimate.market_price == 100_750
    assert estimate.discount_percent > 25
    assert is_deal(estimate, 15)
    assert deal.raw == {"demo": True}
