import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from avito_hunt.domain import Listing
from avito_hunt.normalization import listing_from_payload
from avito_hunt.provider import SourceBatch, validate_batch
from avito_hunt.screening import rejection_reason

logger = logging.getLogger(__name__)


class JsonFeedSource:
    """Reads normalized candidate listings from an explicitly configured JSON endpoint."""

    def __init__(self, url: str, *, timeout: float = 20.0) -> None:
        self.url = url
        self.timeout = timeout

    async def fetch(self) -> SourceBatch:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            payload: Any = response.json()

        items = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("JSON feed must be a list or an object with an 'items' list")

        listings: list[Listing] = []
        rejected: Counter[str] = Counter()
        for item in items:
            if not isinstance(item, dict):
                rejected["invalid_payload"] += 1
                continue
            if reason := rejection_reason(item):
                rejected[reason.value] += 1
                continue
            if listing := listing_from_payload(item):
                listings.append(listing)
            else:
                rejected["invalid_or_not_iphone"] += 1
        if rejected:
            logger.info("Filtered source listings: %s", dict(rejected))
        batch = SourceBatch(
            provider="json-feed",
            listings=tuple(listings),
            fetched_at=datetime.now(UTC),
            received_count=len(items),
            rejected_count=sum(rejected.values()),
        )
        validate_batch(batch)
        return batch
