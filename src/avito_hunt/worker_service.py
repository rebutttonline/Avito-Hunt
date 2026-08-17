import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.logging import configure_logging
from avito_hunt.market import estimate_market, is_deal
from avito_hunt.messages import deal_message
from avito_hunt.source import JsonFeedSource

logger = logging.getLogger(__name__)


async def process_once(database: Database, source: JsonFeedSource, bot: Bot | None) -> None:
    settings = get_settings()
    listings = await source.fetch()
    logger.info("Received %d normalized iPhone listings", len(listings))

    for listing in listings:
        if not await database.insert_listing(listing):
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
        if not is_deal(estimate, settings.deal_discount_percent):
            continue
        assert estimate
        if not bot:
            logger.warning(
                "Deal %s found, but Telegram token is not configured",
                listing.external_id,
            )
            continue
        for chat_id in await database.enabled_chat_ids():
            if await database.notification_exists(chat_id, listing.external_id):
                continue
            try:
                await bot.send_message(
                    chat_id,
                    deal_message(listing, estimate),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                await database.mark_notification(chat_id, listing.external_id)
            except Exception:
                logger.exception("Unable to notify chat_id=%s", chat_id)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.db_url)
    await database.connect()
    await database.ensure_schema()
    bot = Bot(settings.bot_token) if settings.bot_token else None

    try:
        if not settings.source_json_url:
            logger.warning("SOURCE_JSON_URL is empty; worker is waiting for a data source")
            while True:
                await asyncio.sleep(3600)

        source = JsonFeedSource(settings.source_json_url)
        while True:
            try:
                await process_once(database, source, bot)
            except Exception:
                logger.exception("Listing processing cycle failed")
            await asyncio.sleep(settings.source_poll_seconds)
    finally:
        if bot:
            await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
