import pytest

from avito_hunt.screening import RejectionReason, rejection_reason


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"title": "Обменяю iPhone 15 Pro на ноутбук"}, RejectionReason.EXCHANGE),
        ({"title": "iPhone 15 Pro разбит, не включается"}, RejectionReason.BROKEN),
        ({"title": "Копия iPhone 15 Pro на Android"}, RejectionReason.COPY),
        ({"title": "Коробка от iPhone 15 Pro"}, RejectionReason.ACCESSORY),
        ({"title": "iPhone 15 Pro на запчасти"}, RejectionReason.PARTS),
        ({"title": "iPhone 15 Pro, цена от 1000 ₽"}, RejectionReason.PRICE_PLACEHOLDER),
        (
            {"title": "iPhone 15 Pro", "seller_url": "https://www.avito.ru/brands/shop"},
            RejectionReason.BUSINESS_SELLER,
        ),
    ],
)
def test_rejects_non_comparable_offers(payload: dict[str, str], expected: RejectionReason) -> None:
    assert rejection_reason(payload) is expected


def test_does_not_reject_complete_phone_or_negative_exchange_phrase() -> None:
    assert rejection_reason({"title": "iPhone 15 Pro с коробкой"}) is None
    assert (
        rejection_reason(
            {
                "title": "iPhone 15 Pro 256GB",
                "description": "Полный комплект, обмен не интересует",
            }
        )
        is None
    )
