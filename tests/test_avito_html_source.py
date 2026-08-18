from datetime import UTC, datetime

import pytest

from avito_hunt.avito_html_source import (
    parse_avito_cards,
    parse_targets,
    validate_public_category_url,
)

HTML = """
<html><body>
  <div data-marker="item" data-item-id="123456">
    <div>
      <h2 itemProp="name">
        <a data-marker="item-title" itemProp="url"
           title="iPhone 15 Pro Max 256 ГБ"
           href="/moskva/telefony/iphone_15_pro_max_123456?context=tracking">
          iPhone 15 Pro Max 256 ГБ
        </a>
      </h2>
      <p data-marker="item-price" itemProp="offers">
        <meta itemProp="price" content="79900"/>
      </p>
      <p data-marker="item-specific-params">Новый</p>
      <div data-marker="item-location">Москва, Арбат</div>
      <div data-marker="item-date">Сегодня, 12:30</div>
    </div>
  </div>
</body></html>
"""


def test_parses_public_server_rendered_card() -> None:
    fetched_at = datetime(2026, 8, 18, 12, tzinfo=UTC)
    listings, received = parse_avito_cards(HTML, "москва", fetched_at)
    assert received == 1
    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "123456"
    assert listing.model == "iPhone 15 Pro Max"
    assert listing.storage_gb == 256
    assert listing.price == 79_900
    assert listing.condition == "new"
    assert listing.url == "https://www.avito.ru/moskva/telefony/iphone_15_pro_max_123456"


def test_accepts_only_clean_public_avito_category_urls() -> None:
    validate_public_category_url("https://www.avito.ru/moskva/telefony/apple-ASgBAg")
    with pytest.raises(ValueError, match="параметры"):
        validate_public_category_url("https://www.avito.ru/moskva/telefony?q=iphone")
    with pytest.raises(ValueError, match="запрещён"):
        validate_public_category_url("https://www.avito.ru/api/items")
    with pytest.raises(ValueError, match="avito.ru"):
        validate_public_category_url("https://example.test/items")


def test_parses_limited_region_targets() -> None:
    targets = parse_targets(
        "Москва|https://www.avito.ru/moskva/telefony/apple-ASgBAg;"
        "Казань|https://www.avito.ru/kazan/telefony/apple-ASgBAg"
    )
    assert [target.region for target in targets] == ["москва", "казань"]
