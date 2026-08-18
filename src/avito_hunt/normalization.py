import re
from datetime import UTC, datetime
from typing import Any

from avito_hunt.domain import Listing

_IPHONE_MODEL = re.compile(
    r"\b(?:iphone|айфон)\s*(?P<number>16\s*e|1[1-7]|8|x[rs]?|se)"
    r"\s*(?P<variant>pro\s*max|promax|pro|plus|mini|air|max)?\b",
    re.IGNORECASE,
)
_STORAGE = re.compile(r"\b(64|128|256|512|1024)\s*(?:gb|гб|г|гиг(?:абайт(?:а|ов)?)?)\b", re.I)


def normalize_model(title: str) -> str | None:
    match = _IPHONE_MODEL.search(title)
    if not match:
        return None
    number = match.group("number").upper().replace(" ", "")
    if number == "16E":
        number = "16e"
    variant = " ".join((match.group("variant") or "").lower().split())
    if variant == "promax":
        variant = "pro max"
    suffix = f" {variant.title()}" if variant else ""
    return f"iPhone {number}{suffix}"


def normalize_storage(title: str, value: Any = None) -> int | None:
    if value not in (None, ""):
        try:
            storage = int(value)
            return storage if storage in {64, 128, 256, 512, 1024} else None
        except (TypeError, ValueError):
            pass
    match = _STORAGE.search(title)
    return int(match.group(1)) if match else None


def normalize_condition(value: Any) -> str:
    text = str(value or "used").strip().lower()
    if any(marker in text for marker in ("new", "нов", "запечат")):
        return "new"
    if any(marker in text for marker in ("broken", "repair", "на запчаст", "не работает")):
        return "broken"
    return "used"


def parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def listing_from_payload(payload: dict[str, Any]) -> Listing | None:
    title = str(payload.get("title") or "").strip()
    model = normalize_model(title)
    if not model:
        return None

    external_id = str(payload.get("external_id") or payload.get("id") or "").strip()
    url = str(payload.get("url") or "").strip()
    try:
        price = int(float(payload.get("price", 0)))
    except (TypeError, ValueError):
        return None
    if not external_id or not url.startswith(("https://", "http://")) or price <= 0:
        return None

    return Listing(
        external_id=external_id,
        title=title,
        url=url,
        price=price,
        model=model,
        storage_gb=normalize_storage(title, payload.get("storage_gb")),
        condition=normalize_condition(payload.get("condition")),
        region=str(payload.get("region") or "unknown").strip().lower(),
        published_at=parse_datetime(payload.get("published_at")),
        raw=payload,
    )
