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
        if button.callback_data
        and button.callback_data.startswith(("feedback:good:", "feedback:bad:"))
    ]
    assert [button.text for button in feedback_buttons] == ["🔥 Интересно", "😐 Неинтересно"]
    assert {button.callback_data.split(":", 2)[1] for button in feedback_buttons} == {
        "good",
        "bad",
    }
    assert keyboard.inline_keyboard[-1][0].callback_data == "panel:root"
    assert any(
        button.callback_data and button.callback_data.startswith("feedback:comment:")
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_live_card_marks_condition_as_unverified_seller_claim() -> None:
    listing = Listing(
        external_id="live-condition",
        title="iPhone 14 128 ГБ",
        url="https://example.test/live-condition",
        price=50_000,
        model="iPhone 14",
        storage_gb=128,
        condition="new",
        region="москва",
        published_at=datetime.now(UTC),
        raw={"source": "avito-public-html-pilot", "condition": "Новый"},
    )
    estimate = MarketEstimate(
        market_price=60_000,
        discount_amount=10_000,
        discount_percent=Decimal("16.7"),
        comparable_count=12,
        confidence="medium",
    )

    message = deal_message(listing, estimate)

    assert "новый — со слов продавца" in message
    assert "без описания и данных продавца" in message


def test_training_card_is_explicitly_marked_as_archived() -> None:
    listing = Listing(
        external_id="training-card",
        title="iPhone 13 128 ГБ",
        url="https://example.test/training-card",
        price=40_000,
        model="iPhone 13",
        storage_gb=128,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )
    estimate = MarketEstimate(
        market_price=45_000,
        discount_amount=5_000,
        discount_percent=Decimal("11.1"),
        comparable_count=15,
        confidence="medium",
    )

    message = deal_message(listing, estimate, training=True)

    assert "ОБУЧАЮЩАЯ КАРТОЧКА" in message
    assert "может быть уже неактуально" in message
