from datetime import UTC, datetime
from decimal import Decimal

from avito_hunt.domain import Listing, UserPreferences
from avito_hunt.preferences import is_quiet_time, matches_preferences, model_generation


def listing(*, model: str = "iPhone 15 Pro", storage: int = 256) -> Listing:
    return Listing(
        external_id="listing-1",
        title=f"{model} {storage} ГБ",
        url="https://example.test/listing-1",
        price=70_000,
        model=model,
        storage_gb=storage,
        condition="used",
        region="москва",
        published_at=datetime.now(UTC),
    )


def test_default_preferences_track_every_iphone() -> None:
    preferences = UserPreferences(chat_id=1)
    assert matches_preferences(preferences, listing(), Decimal("15.0"))
    assert matches_preferences(
        preferences,
        listing(model="iPhone 17 Air", storage=512),
        Decimal("18.0"),
    )


def test_filters_by_generation_storage_region_and_discount() -> None:
    preferences = UserPreferences(
        chat_id=1,
        model_generations=("15",),
        storage_options=(256,),
        region="москва",
        min_discount_percent=Decimal("20"),
    )
    assert matches_preferences(preferences, listing(), Decimal("20"))
    assert not matches_preferences(preferences, listing(model="iPhone 16 Pro"), Decimal("25"))
    assert not matches_preferences(preferences, listing(storage=512), Decimal("25"))
    assert not matches_preferences(preferences, listing(), Decimal("19.9"))


def test_disabled_user_never_matches() -> None:
    preferences = UserPreferences(chat_id=1, enabled=False)
    assert not matches_preferences(preferences, listing(), Decimal("50"))


def test_groups_x_family_and_16e() -> None:
    assert model_generation("iPhone XS Max") == "X"
    assert model_generation("iPhone XR") == "X"
    assert model_generation("iPhone 16e") == "16"


def test_quiet_hours_can_cross_midnight() -> None:
    preferences = UserPreferences(chat_id=1, quiet_start_hour=23, quiet_end_hour=8)
    assert is_quiet_time(preferences, datetime(2026, 8, 18, 0, tzinfo=UTC))
    assert not is_quiet_time(preferences, datetime(2026, 8, 18, 8, tzinfo=UTC))
