import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.domain import ListingChange
from avito_hunt.logging import configure_logging
from avito_hunt.market import estimate_market
from avito_hunt.messages import deal_keyboard, deal_message
from avito_hunt.preferences import is_quiet_time, matches_preferences
from avito_hunt.provider import ListingSource
from avito_hunt.source import JsonFeedSource

logger = logging.getLogger(__name__)


async def process_once(database: Database, source: ListingSource, bot: Bot | None) -> None:
    settings = get_settings()
    batch = await source.fetch()
    listings = batch.listings
    await database.set_system_state(
        "source",
        {
            "status": "ok",
            "provider": batch.provider,
            "received": batch.received_count,
            "accepted": len(listings),
            "rejected": batch.rejected_count,
            "fetched_at": batch.fetched_at.isoformat(),
        },
    )
    logger.info("Received %d normalized iPhone listings", len(listings))

    for listing in listings:
        if listing.status != "active":
            await database.mark_listing_status(listing.external_id, listing.status)
            continue
        record = await database.record_listing(listing)
        if record.change not in {ListingChange.NEW, ListingChange.PRICE_DROPPED}:
            continue
        prices = await database.comparable_prices(
            listing,
            max_age=timedelta(days=settings.comparable_max_age_days),
        )
        estimate = estimate_market(
            listing,
            prices,
            minimum_count=settings.min_comparable_listings,
        )
        if not estimate or not estimate.is_discounted:
            continue
        if not bot:
            logger.warning(
                "Deal %s found, but Telegram token is not configured",
                listing.external_id,
            )
            continue
        for preferences in await database.enabled_user_preferences():
            if not matches_preferences(preferences, listing, estimate.discount_percent):
                continue
            if is_quiet_time(preferences):
                continue
            if (
                preferences.daily_alert_limit > 0
                and await database.notifications_today(preferences.chat_id)
                >= preferences.daily_alert_limit
            ):
                continue
            event_type = (
                "price_drop" if record.change is ListingChange.PRICE_DROPPED else "new_listing"
            )
            if await database.notification_event_exists(
                preferences.chat_id,
                listing.external_id,
                listing.price,
                event_type,
            ):
                continue
            try:
                await bot.send_message(
                    preferences.chat_id,
                    deal_message(
                        listing,
                        estimate,
                        previous_price=record.previous_price,
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=deal_keyboard(listing),
                )
                await database.mark_notification_event(
                    preferences.chat_id,
                    listing.external_id,
                    listing.price,
                    event_type,
                )
            except Exception:
                logger.exception("Unable to notify chat_id=%s", preferences.chat_id)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.db_url)
    await database.connect()
    await database.ensure_schema()
    bot = Bot(settings.bot_token) if settings.bot_token else None

    try:
        if not settings.source_json_url:
            await database.set_system_state(
                "source",
                {"status": "waiting", "reason": "SOURCE_JSON_URL is empty"},
            )
            logger.warning("SOURCE_JSON_URL is empty; worker is waiting for a data source")
            while True:
                await asyncio.sleep(3600)

        source = JsonFeedSource(settings.source_json_url)
        consecutive_failures = 0
        while True:
            try:
                await process_once(database, source, bot)
                consecutive_failures = 0
            except Exception as error:
                consecutive_failures += 1
                await database.set_system_state(
                    "source",
                    {
                        "status": "error",
                        "consecutive_failures": consecutive_failures,
                        "error_type": type(error).__name__,
                    },
                )
                logger.exception("Listing processing cycle failed")
                if bot and consecutive_failures in {3, 10}:
                    for chat_id in await database.admin_chat_ids():
                        await bot.send_message(
                            chat_id,
                            "🚨 Источник Avito Hunt недоступен: "
                            f"{consecutive_failures} ошибок подряд.",
                        )
            await asyncio.sleep(settings.source_poll_seconds)
    finally:
        if bot:
            await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
