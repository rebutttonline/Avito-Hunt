from avito_hunt.domain import PriceLevel
from avito_hunt.market import price_level
from avito_hunt.risk import assess_listing_risk
from avito_hunt.simulator import demo_estimate


def test_demo_exercises_market_and_risk_explanation() -> None:
    listing, estimate = demo_estimate()
    assert price_level(estimate) in {PriceLevel.GREAT_DEAL, PriceLevel.SUSPICIOUSLY_CHEAP}
    assert assess_listing_risk(listing).issues
    assert listing.url.startswith("https://example.test/")
