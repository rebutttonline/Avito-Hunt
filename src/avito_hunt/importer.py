import csv
import io
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from avito_hunt.domain import Listing
from avito_hunt.normalization import listing_from_payload
from avito_hunt.provider import SourceBatch, validate_batch
from avito_hunt.screening import rejection_reason

MAX_IMPORT_RECORDS = 1_000


def parse_import(data: bytes, filename: str) -> SourceBatch:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".json":
        items = _json_items(data)
    elif suffix == ".csv":
        items = _csv_items(data)
    else:
        raise ValueError("Поддерживаются только файлы .json и .csv")
    if len(items) > MAX_IMPORT_RECORDS:
        raise ValueError(f"В одном файле допускается не более {MAX_IMPORT_RECORDS} записей")

    listings: list[Listing] = []
    rejected: Counter[str] = Counter()
    for item in items:
        if reason := rejection_reason(item):
            rejected[reason.value] += 1
        elif listing := listing_from_payload(item):
            listings.append(listing)
        else:
            rejected["invalid_or_not_iphone"] += 1
    batch = SourceBatch(
        provider="admin-import",
        listings=tuple(listings),
        fetched_at=datetime.now(UTC),
        received_count=len(items),
        rejected_count=sum(rejected.values()),
    )
    validate_batch(batch)
    return batch


def _json_items(data: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Не удалось прочитать JSON") from error
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("JSON должен быть массивом объектов или объектом с массивом items")
    return items


def _csv_items(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV должен быть в кодировке UTF-8") from error
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV не содержит заголовков")
    return [dict(row) for row in reader]
