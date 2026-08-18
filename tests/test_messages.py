from datetime import UTC, datetime
from decimal import Decimal

import pytest

from avito_hunt.domain import Listing, MarketEstimate
from avito_hunt.messages import deal_message


@pytest.mark.parametrize(
    ("discount", "label"),
    [
        (Decimal("10"), "Обычная цена"),
        (Decimal("20"), "Выгодно"),
        (Decimal("30"), "Очень выгодно"),
        (Decimal("40"), "Подозрительно дёшево"),
    ],
)
def test_message_uses_price_level_label(discount: Decimal, label: str) -> None:
    listing = Listing(
        external_id="test",
        title="iPhone 15 Pro Max 256GB",
        url="https://example.test/test",
        price=100_000 - int(discount * 1000),
        model="iPhone 15 Pro Max",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )
    estimate = MarketEstimate(
        market_price=100_000,
        discount_amount=int(discount * 1000),
        discount_percent=discount,
        comparable_count=12,
        confidence="medium",
    )
    assert label in deal_message(listing, estimate)
