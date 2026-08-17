import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.logging import configure_logging

logger = logging.getLogger(__name__)
router = Router()
database: Database


@router.message(Command("start"))
async def start(message: Message) -> None:
    assert message.from_user
    await database.register_user(message.chat.id, message.from_user.username)
    await message.answer(
        "Avito Hunt включён ✅\n\n"
        "Я пришлю уведомление, когда найду iPhone заметно дешевле сопоставимых предложений. "
        "Для остановки уведомлений используйте /stop."
    )


@router.message(Command("stop"))
async def stop(message: Message) -> None:
    await database.disable_user(message.chat.id)
    await message.answer("Уведомления остановлены. Чтобы включить их снова, отправьте /start.")


@router.message(Command("status"))
async def status(message: Message) -> None:
    enabled = await database.user_enabled(message.chat.id)
    text = "включены ✅" if enabled else "выключены ⏸"
    await message.answer(f"Уведомления: {text}")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "/start — включить уведомления\n"
        "/status — проверить состояние\n"
        "/stop — остановить уведомления\n"
        "/help — показать справку"
    )


async def run() -> None:
    global database
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.db_url)
    await database.connect()
    await database.ensure_schema()

    if not settings.bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is empty; bot is waiting for configuration")
        while True:
            await asyncio.sleep(3600)

    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        logger.info("Starting Telegram long polling")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
