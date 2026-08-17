from html import escape

from avito_hunt.domain import Listing, MarketEstimate


def deal_message(listing: Listing, estimate: MarketEstimate) -> str:
    storage = f", {listing.storage_gb} ГБ" if listing.storage_gb else ""
    confidence = "высокая" if estimate.confidence == "high" else "средняя"
    price = f"{listing.price:,}".replace(",", " ")
    market_price = f"{estimate.market_price:,}".replace(",", " ")
    discount = f"{estimate.discount_amount:,}".replace(",", " ")
    return (
        "🔥 <b>Выгодный iPhone</b>\n\n"
        f"<b>{escape(listing.title)}</b>\n"
        f"Цена: <b>{price} ₽</b>\n"
        f"Оценка рынка: {market_price} ₽\n"
        f"Ниже рынка: <b>{discount} ₽ "
        f"({estimate.discount_percent}%)</b>\n"
        f"Характеристики: {escape(listing.model)}{storage}, {escape(listing.condition)}\n"
        f"Регион: {escape(listing.region)}\n"
        f"Аналогов: {estimate.comparable_count}; уверенность: {confidence}\n\n"
        f'<a href="{escape(listing.url, quote=True)}">Открыть объявление</a>\n\n'
        "⚠️ Низкая цена не гарантирует исправность или безопасность сделки."
    )
