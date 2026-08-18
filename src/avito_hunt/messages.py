from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from avito_hunt.deduplication import feedback_key
from avito_hunt.domain import Listing, MarketEstimate, PriceLevel
from avito_hunt.market import price_level
from avito_hunt.risk import assess_listing_risk


def deal_message(
    listing: Listing,
    estimate: MarketEstimate,
    *,
    previous_price: int | None = None,
    demo: bool = False,
) -> str:
    storage = f", {listing.storage_gb} ГБ" if listing.storage_gb else ""
    confidence = "высокая" if estimate.confidence == "high" else "средняя"
    price = f"{listing.price:,}".replace(",", " ")
    market_price = f"{estimate.market_price:,}".replace(",", " ")
    discount = f"{estimate.discount_amount:,}".replace(",", " ")
    level = price_level(estimate)
    labels = {
        PriceLevel.NORMAL: ("📊", "Обычная цена", "цена близка к рынку"),
        PriceLevel.DEAL: ("🔥", "Выгодно", "цена заметно ниже рынка"),
        PriceLevel.GREAT_DEAL: (
            "🚀",
            "Очень выгодно",
            "цена значительно ниже похожих объявлений",
        ),
        PriceLevel.SUSPICIOUSLY_CHEAP: (
            "🚨",
            "Подозрительно дёшево",
            "скидка необычно велика — особенно тщательно проверьте продавца и устройство",
        ),
    }
    icon, label, verdict = labels[level]
    risk = assess_listing_risk(listing)
    risk_labels = {"low": "низкий 🟢", "medium": "средний 🟡", "high": "высокий 🔴"}
    risk_details = "; ".join(escape(issue) for issue in risk.issues[:3])
    risk_line = f"🛡 Риск: <b>{risk_labels[risk.level.value]}</b> ({risk.score}/100)"
    if risk_details:
        risk_line += f"\nПричины: {risk_details}"
    price_change = ""
    if previous_price and previous_price > listing.price:
        old_price = f"{previous_price:,}".replace(",", " ")
        price_change = f"\n⬇️ Цена снижена с {old_price} ₽"
    demo_prefix = "🧪 <b>ДЕМОНСТРАЦИЯ</b>\n" if demo else ""
    return (
        f"{demo_prefix}{icon} <b>{label}</b>\n\n"
        f"<b>{escape(listing.title)}</b>\n"
        f"💰 Цена: <b>{price} ₽</b>\n"
        f"📊 Рыночная оценка: <b>{market_price} ₽</b>\n"
        f"📉 Выгода: <b>{discount} ₽ "
        f"({estimate.discount_percent}%)</b>\n"
        f"📱 {escape(listing.model)}{storage}, {escape(listing.condition)}\n"
        f"📍 {escape(listing.region.title())}{price_change}\n"
        f"{risk_line}\n\n"
        f"<b>Почему это предложение:</b> {verdict}. Расчёт сделан по медиане "
        f"{estimate.comparable_count} сопоставимых объявлений; уверенность: {confidence}.\n\n"
        f'<a href="{escape(listing.url, quote=True)}">Открыть объявление</a>\n\n'
        "⚠️ Не переводите предоплату и проверяйте устройство перед покупкой."
    )


def deal_keyboard(listing: Listing) -> InlineKeyboardMarkup:
    key = feedback_key(listing.external_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть объявление ↗", url=listing.url)],
            [
                InlineKeyboardButton(text="👍 Полезно", callback_data=f"feedback:good:{key}"),
                InlineKeyboardButton(text="👎 Мимо", callback_data=f"feedback:bad:{key}"),
            ],
            [InlineKeyboardButton(text="🚩 Подозрительно", callback_data=f"feedback:risk:{key}")],
        ]
    )
