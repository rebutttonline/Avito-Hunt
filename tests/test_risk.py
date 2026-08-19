from datetime import UTC, datetime

from avito_hunt.domain import Listing, RiskLevel
from avito_hunt.risk import assess_listing_risk


def listing(description: str, **raw: object) -> Listing:
    return Listing(
        external_id="risk-1",
        title="iPhone 15 Pro Max 256 ГБ",
        url="https://example.test/risk-1",
        price=75_000,
        model="iPhone 15 Pro Max",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
        raw={"description": description, **raw},
    )


def test_combines_device_risk_signals() -> None:
    result = assess_listing_risk(
        listing("Face ID не работает, менялся экран, срочно", battery_health=78)
    )
    assert result.level is RiskLevel.HIGH
    assert result.score >= 85
    assert any("Face ID" in issue for issue in result.issues)


def test_does_not_penalize_explicit_no_prepayment() -> None:
    result = assess_listing_risk(listing("Полный комплект, без предоплаты, iCloud отвязан"))
    assert result.level is RiskLevel.LOW
    assert result.score == 0


def test_public_html_new_condition_is_not_treated_as_verified() -> None:
    item = listing("", source="avito-public-html-pilot", condition="Новый")
    item = Listing(
        external_id=item.external_id,
        title=item.title,
        url=item.url,
        price=item.price,
        model=item.model,
        storage_gb=item.storage_gb,
        condition="new",
        region=item.region,
        published_at=item.published_at,
        raw=item.raw,
    )

    result = assess_listing_risk(item)

    assert result.score == 15
    assert any("продавцом" in issue for issue in result.issues)
