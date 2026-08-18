from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from avito_hunt.domain import Listing


@dataclass(frozen=True, slots=True)
class SourceBatch:
    provider: str
    listings: tuple[Listing, ...]
    fetched_at: datetime
    received_count: int
    rejected_count: int = 0
    full_snapshot: bool = False


class ListingSource(Protocol):
    async def fetch(self) -> SourceBatch: ...


class BatchSource:
    def __init__(self, batch: SourceBatch) -> None:
        self.batch = batch

    async def fetch(self) -> SourceBatch:
        return self.batch


def validate_batch(batch: SourceBatch) -> None:
    if not batch.provider.strip():
        raise ValueError("Provider name is required")
    if batch.fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    if batch.received_count < len(batch.listings):
        raise ValueError("received_count cannot be smaller than normalized listings")
    identifiers = [listing.external_id for listing in batch.listings]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Provider batch contains duplicate external IDs")
    for listing in batch.listings:
        if listing.published_at.tzinfo is None:
            raise ValueError(f"Listing {listing.external_id} has a naive timestamp")
        if listing.price <= 0 or not listing.url.startswith(("http://", "https://")):
            raise ValueError(f"Listing {listing.external_id} violates the source contract")


def empty_batch(provider: str) -> SourceBatch:
    return SourceBatch(
        provider=provider,
        listings=(),
        fetched_at=datetime.now(UTC),
        received_count=0,
    )
