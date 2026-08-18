import json
from pathlib import Path

import pytest

from avito_hunt.importer import parse_import

SAMPLE = Path(__file__).parents[1] / "examples" / "import_sample.json"


def payload(external_id: str = "import-1") -> dict[str, object]:
    return {
        "id": external_id,
        "title": "iPhone 15 Pro 256 ГБ",
        "price": 80000,
        "url": f"https://example.test/{external_id}",
        "condition": "used",
        "region": "Москва",
        "published_at": "2026-08-18T10:00:00Z",
    }


def test_imports_json_and_reports_rejections() -> None:
    bad = {**payload("bad"), "title": "Коробка от iPhone 15 Pro"}
    batch = parse_import(json.dumps({"items": [payload(), bad]}).encode(), "sample.json")
    assert batch.received_count == 2
    assert len(batch.listings) == 1
    assert batch.rejected_count == 1


def test_imports_csv() -> None:
    data = (
        "id,title,price,url,condition,region,published_at\n"
        "csv-1,iPhone 14 Pro 256GB,70000,https://example.test/csv-1,used,Казань,"
        "2026-08-18T10:00:00Z\n"
    ).encode()
    batch = parse_import(data, "sample.csv")
    assert batch.received_count == 1
    assert batch.listings[0].model == "iPhone 14 Pro"


def test_rejects_unsupported_import_type() -> None:
    with pytest.raises(ValueError, match="json"):
        parse_import(b"x", "sample.txt")


def test_repository_sample_contains_market_and_candidate() -> None:
    batch = parse_import(SAMPLE.read_bytes(), SAMPLE.name)
    assert batch.received_count == 11
    assert len(batch.listings) == 11
