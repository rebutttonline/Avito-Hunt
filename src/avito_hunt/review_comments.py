from collections.abc import Iterable

REASON_MARKERS: dict[str, tuple[str, ...]] = {
    "цена/маржа": ("цен", "дорог", "дешев", "марж", "прибыл", "перепрод"),
    "состояние": ("состоя", "убит", "царап", "скол", "износ", "аккумуля", "акб"),
    "ремонт/детали": ("ремонт", "разбит", "запчаст", "экран", "face id", "true tone"),
    "продавец": ("продав", "магазин", "центр", "перекуп", "профиль", "отзыв"),
    "комплект": ("короб", "комплект", "чек", "заряд", "кабель"),
    "ликвидность": ("ликвид", "спрос", "модель", "цвет", "памят"),
    "риск": ("риск", "мошен", "подозр", "предоплат", "обман", "копи", "паль"),
}


def analyze_review_comment(comment: str) -> tuple[str, ...]:
    text = comment.casefold()
    return tuple(
        reason for reason, markers in REASON_MARKERS.items() if _contains_any(text, markers)
    )


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)
