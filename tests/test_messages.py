from datetime import UTC, datetime
from decimal import Decimal

import pytest

from avito_hunt.domain import Listing, MarketEstimate
from avito_hunt.messages import deal_keyboard, deal_message


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


def test_message_explains_market_range_scope_and_low_confidence() -> None:
    listing = Listing(
        external_id="explain",
        title="iPhone 15 Pro 256GB",
        url="https://example.test/explain",
        price=75_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="томск",
        published_at=datetime.now(UTC),
    )
    estimate = MarketEstimate(
        market_price=100_000,
        discount_amount=25_000,
        discount_percent=Decimal("25"),
        comparable_count=15,
        confidence="low",
        range_low=95_000,
        range_high=105_000,
        cheaper_than_percent=93,
        market_scope="national",
    )
    message = deal_message(listing, estimate)
    assert "95 000–105 000 ₽" in message
    assert "93%" in message
    assert "рынку России" in message
    assert "уверенность: низкая" in message


def test_deal_keyboard_has_two_reviewer_choices() -> None:
    listing = Listing(
        external_id="feedback",
        title="iPhone 15 Pro 256GB",
        url="https://example.test/feedback",
        price=75_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )
    keyboard = deal_keyboard(listing)
    feedback_buttons = [
        button
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("feedback:")
    ]
    assert [button.text for button in feedback_buttons] == ["🔥 Интересно", "😐 Неинтересно"]
    assert {button.callback_data.split(":", 2)[1] for button in feedback_buttons} == {
        "good",
        "bad",
    }
