import re
from enum import StrEnum
from typing import Any


class RejectionReason(StrEnum):
    EXCHANGE = "exchange"
    BROKEN = "broken"
    COPY = "copy"
    ACCESSORY = "accessory"
    PARTS = "parts"
    PRICE_PLACEHOLDER = "price_placeholder"


_SPACE = re.compile(r"\s+")

_BROKEN = (
    "разбит",
    "не включается",
    "телефон не работает",
    "iphone не работает",
    "айфон не работает",
    "после воды",
    "утоплен",
    "заблокирован icloud",
    "icloud lock",
)
_COPY = ("копия", "реплика", "подделка", "не оригинал", "android под iphone")
_PARTS = ("на запчасти", "на разбор", "донор", "запчасти", "материнская плата")
_ACCESSORY_TITLE = (
    "чехол ",
    "защитное стекло",
    "стекло для",
    "коробка от iphone",
    "коробка для iphone",
    "только коробка",
    "чехол для iphone",
    "макет iphone",
    "муляж iphone",
    "дисплей для iphone",
    "экран для iphone",
    "аккумулятор для iphone",
    "кабель для iphone",
    "зарядка для iphone",
)
_PRICE_PLACEHOLDER = ("цена от", "цена за услугу", "указана за", "первоначальный взнос")
_EXCHANGE_POSITIVE = ("обменяю", "рассмотрю обмен", "возможен обмен", "обмен на")
_EXCHANGE_NEGATIVE = ("без обмена", "обмен не интересует", "не обмен")


def rejection_reason(payload: dict[str, Any]) -> RejectionReason | None:
    title = _normalize(payload.get("title"))
    description = _normalize(payload.get("description"))
    condition = _normalize(payload.get("condition"))
    combined = " ".join((title, description, condition))

    if any(marker in combined for marker in _PARTS):
        return RejectionReason.PARTS
    if any(marker in combined for marker in _BROKEN):
        return RejectionReason.BROKEN
    if any(marker in combined for marker in _COPY):
        return RejectionReason.COPY
    if any(marker in title for marker in _ACCESSORY_TITLE):
        return RejectionReason.ACCESSORY
    if any(marker in combined for marker in _PRICE_PLACEHOLDER):
        return RejectionReason.PRICE_PLACEHOLDER
    if not any(marker in combined for marker in _EXCHANGE_NEGATIVE) and any(
        marker in combined for marker in _EXCHANGE_POSITIVE
    ):
        return RejectionReason.EXCHANGE
    return None


def _normalize(value: Any) -> str:
    return _SPACE.sub(" ", str(value or "").casefold()).strip()
