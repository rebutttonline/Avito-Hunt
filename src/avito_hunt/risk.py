import re
from typing import Any

from avito_hunt.domain import Listing, RiskAssessment, RiskLevel

_BATTERY = re.compile(r"(?:акб|аккумулятор|battery|ёмкость|емкость)\D{0,12}(\d{2,3})\s*%", re.I)


def assess_listing_risk(listing: Listing) -> RiskAssessment:
    text = _listing_text(listing)
    for safe_phrase in (
        "без предоплаты",
        "предоплата не нужна",
        "icloud отвязан",
        "айклауд отвязан",
        "icloud чистый",
    ):
        text = text.replace(safe_phrase, "")
    issues: list[str] = []
    score = 0

    if listing.raw.get("source") == "avito-public-html-pilot":
        score += 10
        issues.append("описание и данные продавца пока не проверены")
        if listing.condition == "new":
            score += 5
            issues.append("состояние «новое» указано продавцом")

    battery = _battery_health(text, listing.raw)
    if battery is not None and battery < 80:
        score += 35
        issues.append(f"аккумулятор сильно изношен: {battery}%")
    elif battery is not None and battery < 85:
        score += 20
        issues.append(f"аккумулятор требует внимания: {battery}%")

    checks = (
        (
            ("face id не работает", "без face id", "фейс айди не работает"),
            30,
            "не работает Face ID",
        ),
        (("true tone не работает", "без true tone"), 15, "не работает True Tone"),
        (
            ("менялся экран", "замена экрана", "дисплей заменен", "дисплей заменён"),
            20,
            "экран заменён",
        ),
        (("восстановленный", "восстановлен", "refurbished"), 25, "восстановленное устройство"),
        (("нет коробки", "без коробки"), 5, "нет коробки"),
        (("только телефон", "без комплекта"), 5, "неполный комплект"),
        (("icloud", "айклауд"), 35, "упоминается iCloud — проверьте отвязку"),
        (("предоплата", "задаток", "бронь по переводу"), 40, "продавец упоминает предоплату"),
        (("срочно", "сегодня дешевле", "нужны деньги"), 5, "продавец торопит с покупкой"),
    )
    for markers, points, issue in checks:
        if any(marker in text for marker in markers):
            score += points
            issues.append(issue)

    score = min(score, 100)
    if score >= 50:
        level = RiskLevel.HIGH
    elif score >= 20:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW
    return RiskAssessment(level=level, score=score, issues=tuple(dict.fromkeys(issues)))


def _listing_text(listing: Listing) -> str:
    values = (
        listing.title,
        listing.raw.get("description"),
        listing.raw.get("condition"),
        listing.raw.get("completeness"),
    )
    return " ".join(str(value or "").casefold() for value in values)


def _battery_health(text: str, raw: dict[str, Any]) -> int | None:
    for key in ("battery_health", "battery_percent", "batteryHealth"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                numeric = int(str(value).rstrip("%"))
                if 0 < numeric <= 100:
                    return numeric
            except ValueError:
                pass
    match = _BATTERY.search(text)
    return int(match.group(1)) if match and int(match.group(1)) <= 100 else None
