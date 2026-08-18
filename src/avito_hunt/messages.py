from html import escape

from avito_hunt.domain import Listing, MarketEstimate


def deal_message(listing: Listing, estimate: MarketEstimate) -> str:
    storage = f", {listing.storage_gb} ГБ" if listing.storage_gb else ""
    confidence = "высокая" if estimate.confidence == "high" else "средняя"
    price = f"{listing.price:,}".replace(",", " ")
    market_price = f"{estimate.market_price:,}".replace(",", " ")
    discount = f"{estimate.discount_amount:,}".replace(",", " ")
    if estimate.discount_percent >= 30:
        verdict = "цена экстремально ниже рынка — тщательно проверьте продавца"
    elif estimate.discount_percent >= 20:
        verdict = "очень выгодная цена относительно похожих объявлений"
    else:
        verdict = "цена заметно ниже рынка"
    return (
        "🔥 <b>Найден выгодный iPhone</b>\n\n"
        f"<b>{escape(listing.title)}</b>\n"
        f"💰 Цена: <b>{price} ₽</b>\n"
        f"📊 Рыночная оценка: <b>{market_price} ₽</b>\n"
        f"📉 Выгода: <b>{discount} ₽ "
        f"({estimate.discount_percent}%)</b>\n"
        f"📱 {escape(listing.model)}{storage}, {escape(listing.condition)}\n"
        f"📍 {escape(listing.region.title())}\n\n"
        f"<b>Почему это предложение:</b> {verdict}. Расчёт сделан по медиане "
        f"{estimate.comparable_count} сопоставимых объявлений; уверенность: {confidence}.\n\n"
        f'<a href="{escape(listing.url, quote=True)}">Открыть объявление</a>\n\n'
        "⚠️ Не переводите предоплату и проверяйте устройство перед покупкой."
    )
