import pytest

from avito_hunt.database import SCHEMA_SQL, Database


def test_decodes_asyncpg_jsonb_string() -> None:
    assert Database.decode_json_object('{"status":"waiting","received":0}') == {
        "status": "waiting",
        "received": 0,
    }


def test_accepts_predecoded_json_object() -> None:
    assert Database.decode_json_object({"status": "ok"}) == {"status": "ok"}


def test_rejects_non_object_system_state() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        Database.decode_json_object('["unexpected"]')


def test_schema_persists_feedback_learning_context() -> None:
    assert "decision_context JSONB" in SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reviewer_models" in SCHEMA_SQL


def test_schema_separates_market_data_by_provider() -> None:
    assert "source_provider TEXT NOT NULL" in SCHEMA_SQL
    assert "SET source_provider = 'demo'" in SCHEMA_SQL
    assert "listings_provider_comparable_idx" in SCHEMA_SQL
