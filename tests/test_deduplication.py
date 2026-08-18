from datetime import UTC, datetime

from avito_hunt.deduplication import canonical_url, is_specific_listing_url, relist_fingerprint
from avito_hunt.domain import Listing


def listing(external_id: str, raw: dict[str, object]) -> Listing:
    return Listing(
        external_id=external_id,
        title="iPhone 15 Pro 256 ГБ",
        url=f"https://www.avito.ru/moskva/telefony/{external_id}?utm_source=test#photo",
        price=75_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
        raw=raw,
    )


def test_canonical_url_removes_tracking_and_fragment() -> None:
    value = canonical_url("HTTPS://WWW.AVITO.RU/item/123/?utm_source=x#photo")
    assert value == "https://www.avito.ru/item/123"
    assert is_specific_listing_url(value)
    assert not is_specific_listing_url("https://www.avito.ru/")


def test_relist_fingerprint_survives_changed_external_id() -> None:
    first = listing("one", {"seller_id": "seller-7"})
    second = listing("two", {"seller": {"id": "seller-7"}})
    assert relist_fingerprint(first) == relist_fingerprint(second)


def test_relist_fingerprint_requires_stable_seller_id() -> None:
    assert relist_fingerprint(listing("one", {})) is None
