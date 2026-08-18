from dataclasses import replace
from datetime import UTC, datetime

import pytest

from avito_hunt.domain import Listing
from avito_hunt.provider import SourceBatch, validate_batch


def source_listing(external_id: str = "provider-1") -> Listing:
    return Listing(
        external_id=external_id,
        title="iPhone 15 Pro 256 ГБ",
        url=f"https://example.test/{external_id}",
        price=80_000,
        model="iPhone 15 Pro",
        storage_gb=256,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )


def test_provider_contract_accepts_valid_batch() -> None:
    batch = SourceBatch("licensed-provider", (source_listing(),), datetime.now(UTC), 1)
    validate_batch(batch)


def test_provider_contract_rejects_duplicate_ids() -> None:
    item = source_listing()
    batch = SourceBatch("licensed-provider", (item, replace(item)), datetime.now(UTC), 2)
    with pytest.raises(ValueError, match="duplicate"):
        validate_batch(batch)


def test_provider_contract_requires_aware_timestamp() -> None:
    batch = SourceBatch("licensed-provider", (), datetime(2026, 8, 18), 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_batch(batch)
