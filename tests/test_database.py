import pytest

from avito_hunt.database import Database


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
