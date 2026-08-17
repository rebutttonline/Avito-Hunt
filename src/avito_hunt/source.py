from typing import Any

import httpx

from avito_hunt.domain import Listing
from avito_hunt.normalization import listing_from_payload


class JsonFeedSource:
    """Reads normalized candidate listings from an explicitly configured JSON endpoint."""

    def __init__(self, url: str, *, timeout: float = 20.0) -> None:
        self.url = url
        self.timeout = timeout

    async def fetch(self) -> list[Listing]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            payload: Any = response.json()

        items = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("JSON feed must be a list or an object with an 'items' list")

        listings: list[Listing] = []
        for item in items:
            if isinstance(item, dict) and (listing := listing_from_payload(item)):
                listings.append(listing)
        return listings
