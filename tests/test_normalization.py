from avito_hunt.normalization import listing_from_payload, normalize_model, normalize_storage


def test_normalizes_iphone_model_and_storage() -> None:
    assert normalize_model("Apple iPhone 15 Pro Max 256 ГБ") == "iPhone 15 Pro Max"
    assert normalize_storage("Apple iPhone 15 Pro Max 256 ГБ") == 256


def test_rejects_non_iphone_payload() -> None:
    assert (
        listing_from_payload(
            {"id": "1", "title": "Чехол для телефона", "price": 1000, "url": "https://x"}
        )
        is None
    )


def test_builds_listing_from_valid_payload() -> None:
    listing = listing_from_payload(
        {
            "id": "abc",
            "title": "iPhone 14 Pro 256GB",
            "price": "65000",
            "url": "https://example.test/abc",
            "condition": "Б/у",
            "region": "Москва",
            "published_at": "2026-08-17T10:00:00Z",
        }
    )
    assert listing is not None
    assert listing.model == "iPhone 14 Pro"
    assert listing.storage_gb == 256
    assert listing.condition == "used"
    assert listing.region == "москва"
