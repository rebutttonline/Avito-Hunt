import json

import httpx
import pytest

from avito_hunt.parse_bot_source import PARSE_BOT_PROVIDER, ParseBotSource


@pytest.mark.asyncio
async def test_fetches_and_normalizes_parse_bot_search_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "test-key"
        assert request.headers["API-Snapshot-Version"] == "129"
        assert request.url.params["location"] == "novokuznetsk"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "items": [
                        {
                            "id": "123",
                            "title": "iPhone 15 Pro Max 256 ГБ",
                            "url": "/novokuznetsk/telefony/iphone_123",
                            "price": 79_900,
                            "currency": "RUB",
                            "description_preview": "Личный телефон, без обмена",
                        },
                        {
                            "id": "124",
                            "title": "Коробка от iPhone 15 Pro Max 256 ГБ",
                            "url": "https://www.avito.ru/item/124",
                            "price": 1_500,
                        },
                    ]
                },
            },
        )

    source = ParseBotSource(
        "test-key",
        transport=httpx.MockTransport(handler),
    )
    batch = await source.fetch()

    assert batch.provider == PARSE_BOT_PROVIDER
    assert batch.received_count == 2
    assert batch.rejected_count == 1
    assert len(batch.listings) == 1
    listing = batch.listings[0]
    assert listing.external_id == "123"
    assert listing.model == "iPhone 15 Pro Max"
    assert listing.storage_gb == 256
    assert listing.region == "novokuznetsk"
    assert listing.url == "https://www.avito.ru/novokuznetsk/telefony/iphone_123"


@pytest.mark.asyncio
async def test_rejects_unsuccessful_parse_bot_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"status": "error"}).encode(),
            headers={"content-type": "application/json"},
        )

    source = ParseBotSource("test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="unsuccessful"):
        await source.fetch()
