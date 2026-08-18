from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from avito_hunt.domain import Listing, UserPreferences

MODEL_GENERATIONS = ("17", "16", "15", "14", "13", "12", "11", "X", "SE", "8")
STORAGE_OPTIONS = (64, 128, 256, 512, 1024)


def model_generation(model: str) -> str:
    value = model.removeprefix("iPhone ").split(maxsplit=1)[0]
    if value in {"XR", "XS"}:
        return "X"
    if value.lower().endswith("e") and value[:-1].isdigit():
        return value[:-1]
    return value


def matches_preferences(
    preferences: UserPreferences,
    listing: Listing,
    discount_percent: Decimal,
) -> bool:
    if not preferences.enabled:
        return False
    if discount_percent < preferences.min_discount_percent:
        return False
    if (
        preferences.model_generations
        and model_generation(listing.model) not in preferences.model_generations
    ):
        return False
    if preferences.storage_options and listing.storage_gb not in preferences.storage_options:
        return False
    return not preferences.region or listing.region.casefold() == preferences.region.casefold()


def is_quiet_time(
    preferences: UserPreferences,
    now: datetime | None = None,
) -> bool:
    if preferences.quiet_start_hour is None or preferences.quiet_end_hour is None:
        return False
    local = now or datetime.now(ZoneInfo("Europe/Moscow"))
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo("Europe/Moscow"))
    hour = local.astimezone(ZoneInfo("Europe/Moscow")).hour
    start = preferences.quiet_start_hour
    end = preferences.quiet_end_hour
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def format_models(values: tuple[str, ...]) -> str:
    return "все iPhone" if not values else ", ".join(f"iPhone {value}" for value in values)


def format_storage(values: tuple[int, ...]) -> str:
    if not values:
        return "любая"
    return ", ".join("1 ТБ" if value == 1024 else f"{value} ГБ" for value in values)


def format_discount(value: Decimal) -> str:
    return f"{value.normalize()}%"
