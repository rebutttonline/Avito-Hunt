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
    confidence = {"high": "высокая", "medium": "средняя", "low": "низкая"}.get(
        estimate.confidence, "неизвестная"
    )
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
    range_line = ""
    if estimate.range_low is not None and estimate.range_high is not None:
        low = f"{estimate.range_low:,}".replace(",", " ")
        high = f"{estimate.range_high:,}".replace(",", " ")
        range_line = f"\nОбычный диапазон: <b>{low}–{high} ₽</b>"
    percentile_line = ""
    if estimate.cheaper_than_percent is not None:
        percentile_line = (
            f"\nЦена ниже, чем у <b>{estimate.cheaper_than_percent}%</b> похожих предложений"
        )
    scope_labels = {
        "exact_region": "вашему региону",
        "nearby_regions": "вашему и соседним регионам",
        "national": "рынку России",
    }
    scope = scope_labels.get(estimate.market_scope, "сопоставимому рынку")
    condition_labels = {
        "new": "новый — со слов продавца",
        "used": "б/у",
        "broken": "повреждён или на запчасти",
    }
    condition = condition_labels.get(listing.condition, listing.condition)
    data_note = ""
    if listing.raw.get("source") == "avito-public-html-pilot":
        data_note = "\n🔎 Проверка: краткая карточка Avito, без описания и данных продавца"
    return (
        f"{demo_prefix}{icon} <b>{label}</b>\n\n"
        f"<b>{escape(listing.title)}</b>\n"
        f"💰 Цена: <b>{price} ₽</b>\n"
        f"📊 Рыночная оценка: <b>{market_price} ₽</b>{range_line}{percentile_line}\n"
        f"📉 Выгода: <b>{discount} ₽ "
        f"({estimate.discount_percent}%)</b>\n"
        f"📱 {escape(listing.model)}{storage}, {escape(condition)}\n"
        f"📍 {escape(listing.region.title())}{price_change}\n"
        f"{risk_line}{data_note}\n\n"
        f"<b>Почему это предложение:</b> {verdict}. Расчёт сделан по медиане "
        f"{estimate.comparable_count} объявлений по {scope}; уверенность: {confidence}.\n\n"
        f'<a href="{escape(listing.url, quote=True)}">Открыть объявление</a>\n\n'
        "⚠️ Не переводите предоплату и проверяйте устройство перед покупкой."
    )


def deal_keyboard(listing: Listing) -> InlineKeyboardMarkup:
    key = feedback_key(listing.external_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть объявление ↗", url=listing.url)],
            [
                InlineKeyboardButton(text="🔥 Интересно", callback_data=f"feedback:good:{key}"),
                InlineKeyboardButton(text="😐 Неинтересно", callback_data=f"feedback:bad:{key}"),
            ],
            [InlineKeyboardButton(text="🏹 Вернуться в Avito Hunt", callback_data="panel:root")],
        ]
    )
