import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from avito_hunt.domain import Listing
from avito_hunt.normalization import listing_from_payload
from avito_hunt.provider import SourceBatch, validate_batch
from avito_hunt.screening import rejection_reason

logger = logging.getLogger(__name__)

PARSE_BOT_PROVIDER = "parse-bot-avito"
PARSE_BOT_SEARCH_URL = (
    "https://api.parse.bot/scraper/b54ad12b-11e9-48dd-a911-3dc6465949c4/search_items"
)


class ParseBotSource:
    """Reads Avito search results from Parse.bot's structured search API."""

    def __init__(
        self,
        api_key: str,
        *,
        query: str = "iphone",
        category: str = "telefony",
        location: str = "novokuznetsk",
        price_min: int = 1_000,
        price_max: int = 100_000,
        max_pages: int = 1,
        snapshot_version: str = "129",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Parse.bot API key is required")
        self.api_key = api_key.strip()
        self.query = query.strip()
        self.category = category.strip()
        self.location = location.strip()
        self.price_min = price_min
        self.price_max = price_max
        self.max_pages = max_pages
        self.snapshot_version = snapshot_version.strip()
        self.timeout = timeout
        self.transport = transport

    async def fetch(self) -> SourceBatch:
        fetched_at = datetime.now(UTC)
        raw_items: list[dict[str, Any]] = []
        headers = {
            "X-API-Key": self.api_key,
            "API-Snapshot-Version": self.snapshot_version,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for page in range(1, self.max_pages + 1):
                response = await client.get(
                    PARSE_BOT_SEARCH_URL,
                    headers=headers,
                    params={
                        "page": page,
                        "query": self.query,
                        "category": self.category,
                        "location": self.location,
                        "price_min": self.price_min,
                        "price_max": self.price_max,
                    },
                )
                response.raise_for_status()
                payload: Any = response.json()
                items = _extract_items(payload)
                raw_items.extend(items)
                if not items:
                    break

        listings: list[Listing] = []
        rejected: Counter[str] = Counter()
        seen_ids: set[str] = set()
        for item in raw_items:
            normalized = _normalized_payload(item, self.location, fetched_at)
            external_id = str(normalized.get("id") or "")
            if not external_id or external_id in seen_ids:
                rejected["invalid_or_duplicate_id"] += 1
                continue
            seen_ids.add(external_id)
            if reason := rejection_reason(normalized):
                rejected[reason.value] += 1
                continue
            if listing := listing_from_payload(normalized):
                listings.append(listing)
            else:
                rejected["invalid_or_not_iphone"] += 1

        if rejected:
            logger.info("Filtered Parse.bot listings: %s", dict(rejected))
        batch = SourceBatch(
            provider=PARSE_BOT_PROVIDER,
            listings=tuple(listings),
            fetched_at=fetched_at,
            received_count=len(raw_items),
            rejected_count=sum(rejected.values()),
        )
        validate_batch(batch)
        return batch


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("Parse.bot returned an unsuccessful response")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Parse.bot response does not contain data.items")
    return [item for item in data["items"] if isinstance(item, dict)]


def _normalized_payload(
    item: dict[str, Any], location: str, fetched_at: datetime
) -> dict[str, Any]:
    url = str(item.get("url") or "").strip()
    if url.startswith("/"):
        url = urljoin("https://www.avito.ru", url)
    description = item.get("description") or item.get("description_preview") or ""
    return {
        **item,
        "id": item.get("id") or item.get("item_id"),
        "title": item.get("title"),
        "url": url,
        "price": item.get("price"),
        "description": description,
        "condition": item.get("condition") or "used",
        "region": item.get("region") or item.get("location") or location,
        # The search endpoint does not guarantee a publication timestamp. Treat the
        # first API observation as the listing timestamp rather than inventing one.
        "published_at": item.get("published_at") or fetched_at.isoformat(),
        "seller_kind": item.get("seller_kind") or item.get("seller_type"),
        "source": PARSE_BOT_PROVIDER,
    }
