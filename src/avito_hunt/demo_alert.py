import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

from aiogram import Bot

from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.domain import Listing
from avito_hunt.logging import configure_logging
from avito_hunt.worker_service import process_once

logger = logging.getLogger(__name__)


class DemoSource:
    def __init__(self, listings: list[Listing]) -> None:
        self.listings = listings

    async def fetch(self) -> list[Listing]:
        return self.listings


def build_demo_listings(run_id: str) -> list[Listing]:
    now = datetime.now(UTC)
    market_prices = [
        98_000,
        99_000,
        99_500,
        100_000,
        100_500,
        101_000,
        101_500,
        102_000,
        103_000,
        104_000,
    ]
    listings = [
        Listing(
            external_id=f"demo-{run_id}-market-{index}",
            title="iPhone 15 Pro 256 ГБ · тестовый аналог",
            url="https://www.avito.ru/",
            price=price,
            model="iPhone 15 Pro",
            storage_gb=256,
            condition="used",
            region="москва",
            published_at=now,
            raw={"demo": True},
        )
        for index, price in enumerate(market_prices, start=1)
    ]
    listings.append(
        Listing(
            external_id=f"demo-{run_id}-deal",
            title="🧪 ТЕСТ · iPhone 15 Pro 256 ГБ",
            url="https://www.avito.ru/",
            price=75_000,
            model="iPhone 15 Pro",
            storage_gb=256,
            condition="used",
            region="москва",
            published_at=now,
            raw={"demo": True},
        )
    )
    return listings


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for the demo alert")

    database = Database(settings.db_url)
    bot = Bot(settings.bot_token)
    await database.connect()
    await database.ensure_schema()
    try:
        users = await database.enabled_chat_ids()
        if not users:
            raise RuntimeError("No active bot users. Send /start to the bot first.")
        run_id = uuid4().hex[:12]
        await process_once(database, DemoSource(build_demo_listings(run_id)), bot)
        logger.info("Demo alert run %s completed for %d active user(s)", run_id, len(users))
    finally:
        await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
