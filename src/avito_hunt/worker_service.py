import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta

from aiogram import Bot

from avito_hunt.avito_html_source import (
    AVITO_PRIVATE_HTML_PROVIDER,
    AvitoHtmlSource,
    parse_targets,
)
from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.domain import ListingChange
from avito_hunt.learning import decision_context
from avito_hunt.logging import configure_logging
from avito_hunt.market import estimate_market_hierarchical
from avito_hunt.messages import deal_keyboard, deal_message
from avito_hunt.parse_bot_source import ParseBotSource
from avito_hunt.preferences import is_quiet_time, matches_preferences
from avito_hunt.provider import ListingSource
from avito_hunt.source import JsonFeedSource

logger = logging.getLogger(__name__)


async def notify_admins(database: Database, bot: Bot, text: str) -> None:
    for chat_id in await database.admin_chat_ids():
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Unable to send source status to admin chat_id=%s", chat_id)


async def process_once(
    database: Database,
    source: ListingSource,
    bot: Bot | None,
    *,
    update_source_state: bool = True,
) -> None:
    settings = get_settings()
    batch = await source.fetch()
    listings = batch.listings
    if update_source_state:
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

    candidates = []
    for listing in listings:
        if listing.status != "active":
            await database.mark_listing_status(listing.external_id, listing.status)
            continue
        record = await database.record_listing(listing, batch.provider)
        if record.change is ListingChange.DUPLICATE:
            continue
        candidates.append((listing, record))

    # Persist the complete batch before estimating prices. This makes the result
    # independent of card order and lets unchanged cards become eligible after
    # enough comparable listings have accumulated or a user changes preferences.
    users = await database.enabled_user_preferences()
    for listing, record in candidates:
        if (
            batch.provider == AVITO_PRIVATE_HTML_PROVIDER
            and batch.fetched_at - listing.published_at
            > timedelta(minutes=settings.avito_scraper_max_listing_age_minutes)
        ):
            logger.info(
                "Skipped stale live alert external_id=%s published_at=%s",
                listing.external_id,
                listing.published_at.isoformat(),
            )
            continue
        cohorts = await database.comparable_price_cohorts(
            listing,
            max_age=timedelta(days=settings.comparable_max_age_days),
            source_provider=batch.provider,
        )
        estimate = estimate_market_hierarchical(
            listing,
            cohorts,
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
        for preferences in users:
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
            if event_type == "new_listing":
                already_sent = await database.listing_notification_exists(
                    preferences.chat_id,
                    listing.external_id,
                )
            else:
                already_sent = await database.notification_event_exists(
                    preferences.chat_id,
                    listing.external_id,
                    listing.price,
                    event_type,
                )
            if already_sent:
                continue
            if await database.similar_offer_notification_exists(
                preferences.chat_id,
                listing,
            ):
                logger.info(
                    "Suppressed likely relist external_id=%s for chat_id=%s",
                    listing.external_id,
                    preferences.chat_id,
                )
                continue
            try:
                await bot.send_message(
                    preferences.chat_id,
                    deal_message(
                        listing,
                        estimate,
                        previous_price=(
                            record.previous_price if event_type == "price_drop" else None
                        ),
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
                    decision_context(listing, estimate),
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
        source: ListingSource
        interval = settings.source_poll_seconds
        pilot_expires_at: datetime | None = None
        if settings.parse_bot_key:
            source = ParseBotSource(
                settings.parse_bot_key,
                query=settings.parse_bot_query,
                category=settings.parse_bot_category,
                location=settings.parse_bot_location,
                price_min=settings.parse_bot_price_min,
                price_max=settings.parse_bot_price_max,
                max_pages=settings.parse_bot_max_pages,
                snapshot_version=settings.parse_bot_snapshot_version,
            )
            interval = max(interval, settings.parse_bot_min_interval_seconds)
            logger.info(
                "Parse.bot source enabled for %s; interval=%ds; pages=%d",
                settings.parse_bot_location,
                interval,
                settings.parse_bot_max_pages,
            )
        elif settings.source_json_url:
            source = JsonFeedSource(settings.source_json_url)
        elif settings.avito_scraper_enabled:
            pilot_expires_at = settings.avito_scraper_expires_at
            if not pilot_expires_at or pilot_expires_at.tzinfo is None:
                raise RuntimeError("AVITO_SCRAPER_EXPIRES_AT must be timezone-aware")
            source = AvitoHtmlSource(parse_targets(settings.avito_scraper_targets))
            interval = max(interval, settings.avito_scraper_min_interval_seconds)
            logger.warning(
                "Limited Avito HTML pilot enabled until %s; interval=%ds",
                pilot_expires_at.isoformat(),
                interval,
            )
        else:
            await database.set_system_state(
                "source",
                {"status": "waiting", "reason": "No listing source configured"},
            )
            logger.warning("No listing source configured; worker is waiting")
            while True:
                await asyncio.sleep(3600)

        consecutive_failures = 0
        while True:
            if pilot_expires_at and datetime.now(UTC) >= pilot_expires_at:
                await database.set_system_state(
                    "source",
                    {
                        "status": "expired",
                        "provider": AVITO_PRIVATE_HTML_PROVIDER,
                        "expired_at": pilot_expires_at.isoformat(),
                    },
                )
                logger.warning("Avito HTML pilot expired and stopped automatically")
                while True:
                    await asyncio.sleep(3600)
            try:
                previous_failures = consecutive_failures
                await process_once(database, source, bot)
                consecutive_failures = 0
                if bot and previous_failures >= 3:
                    await notify_admins(
                        database,
                        bot,
                        "✅ Источник Avito Hunt снова доступен. Проверка объявлений "
                        "продолжилась автоматически.",
                    )
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
                    await notify_admins(
                        database,
                        bot,
                        "⚠️ Avito временно не отвечает: "
                        f"{consecutive_failures} ошибок подряд. Бот работает и повторит "
                        "проверку автоматически — ничего делать не нужно.",
                    )
            backoff = min(2 ** min(consecutive_failures, 5), 36) if consecutive_failures else 1
            jitter = secrets.randbelow(31) if settings.avito_scraper_enabled else 0
            await asyncio.sleep(interval * backoff + jitter)
    finally:
        if bot:
            await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
