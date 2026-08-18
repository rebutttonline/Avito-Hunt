import json
from pathlib import Path

from avito_hunt.domain import PriceLevel
from avito_hunt.market import estimate_market, price_level
from avito_hunt.normalization import listing_from_payload

FIXTURE = Path(__file__).parent / "fixtures" / "iphone_market.json"


def load_items() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text())["items"]


def test_synthetic_feed_contains_only_fictional_urls() -> None:
    items = load_items()
    assert len(items) == 24
    assert all(str(item["url"]).startswith("https://example.test/") for item in items)


def test_synthetic_feed_normalizes_varied_titles_and_rejects_noise() -> None:
    listings = [listing_from_payload(item) for item in load_items()]
    accepted = [listing for listing in listings if listing]
    rejected = [listing for listing in listings if not listing]

    assert len(accepted) == 18
    assert len(rejected) == 6
    assert {listing.model for listing in accepted[:12]} == {"iPhone 15 Pro Max"}
    assert all(listing.storage_gb == 256 for listing in accepted[:12])


def test_four_price_levels_against_synthetic_market() -> None:
    items = load_items()
    baseline = [listing_from_payload(item) for item in items[:12]]
    candidates = {str(item["id"]): listing_from_payload(item) for item in items[12:16]}
    prices = [listing.price for listing in baseline if listing]

    expected = {
        "syn-normal": PriceLevel.NORMAL,
        "syn-deal": PriceLevel.DEAL,
        "syn-great": PriceLevel.GREAT_DEAL,
        "syn-suspicious": PriceLevel.SUSPICIOUSLY_CHEAP,
    }
    for external_id, level in expected.items():
        listing = candidates[external_id]
        assert listing
        estimate = estimate_market(listing, prices, minimum_count=10)
        assert estimate
        assert price_level(estimate) is level
