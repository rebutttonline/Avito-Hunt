from datetime import UTC, datetime

from avito_hunt.domain import Listing
from avito_hunt.market import estimate_market


def demo_market() -> tuple[Listing, list[int]]:
    listing = Listing(
        external_id="demo-preview",
        title="iPhone 15 Pro Max 256 ГБ · тестовое объявление",
        url="https://example.test/avito-hunt-demo",
        price=79_900,
        model="iPhone 15 Pro Max",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
        raw={
            "description": "Аккумулятор 82%, экран заменён. Полный комплект, без предоплаты.",
            "battery_health": 82,
            "demo": True,
        },
    )
    comparable_prices = [
        105_000,
        106_500,
        107_000,
        108_000,
        108_500,
        109_000,
        109_500,
        110_000,
        111_000,
        112_000,
        113_000,
        114_000,
    ]
    return listing, comparable_prices


def demo_estimate():
    listing, prices = demo_market()
    estimate = estimate_market(listing, prices, minimum_count=10)
    assert estimate
    return listing, estimate
