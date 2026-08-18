import asyncio
import logging
from contextlib import suppress
from decimal import Decimal

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from avito_hunt.config import get_settings
from avito_hunt.database import Database
from avito_hunt.domain import UserPreferences
from avito_hunt.logging import configure_logging
from avito_hunt.preferences import (
    MODEL_GENERATIONS,
    STORAGE_OPTIONS,
    format_discount,
    format_models,
    format_storage,
)

logger = logging.getLogger(__name__)
router = Router()
database: Database
waiting_for_region: dict[int, int] = {}

REGIONS = {
    "moscow": "москва",
    "spb": "санкт-петербург",
    "kazan": "казань",
    "ekb": "екатеринбург",
    "nsk": "новосибирск",
}


def panel_text(preferences: UserPreferences) -> str:
    state = "включены ✅" if preferences.enabled else "приостановлены ⏸"
    return (
        "🏹 <b>Avito Hunt</b>\n\n"
        f"Уведомления: <b>{state}</b>\n"
        "Я проверяю новые объявления iPhone и показываю предложения заметно ниже рынка.\n\n"
        "Используйте кнопки под этим сообщением — панель будет обновляться без новых сообщений."
    )


def panel_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Приостановить" if enabled else "▶️ Продолжить"
    toggle_data = "panel:pause" if enabled else "panel:resume"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:root")],
            [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
            [InlineKeyboardButton(text="📊 Статус", callback_data="panel:status")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="panel:help")],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Модели iPhone", callback_data="settings:models")],
            [InlineKeyboardButton(text="💾 Объём памяти", callback_data="settings:storage")],
            [InlineKeyboardButton(text="📍 Регион", callback_data="settings:region")],
            [InlineKeyboardButton(text="📉 Минимальная скидка", callback_data="settings:discount")],
            [InlineKeyboardButton(text="← Назад", callback_data="panel:root")],
        ]
    )


def models_keyboard(selected: tuple[str, ...]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if value in selected else ''}iPhone {value}",
                callback_data=f"model:{value}",
            )
            for value in MODEL_GENERATIONS[index : index + 2]
        ]
        for index in range(0, len(MODEL_GENERATIONS), 2)
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="📱 Все модели", callback_data="model:all")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:root")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def storage_keyboard(selected: tuple[int, ...]) -> InlineKeyboardMarkup:
    buttons = []
    for value in STORAGE_OPTIONS:
        label = "1 ТБ" if value == 1024 else f"{value} ГБ"
        if value in selected:
            label = f"✅ {label}"
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"storage:{value}"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons[:3],
            buttons[3:],
            [InlineKeyboardButton(text="💾 Любая память", callback_data="storage:all")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:root")],
        ]
    )


def region_keyboard(current: str | None) -> InlineKeyboardMarkup:
    labels = {
        "moscow": "Москва",
        "spb": "Санкт-Петербург",
        "kazan": "Казань",
        "ekb": "Екатеринбург",
        "nsk": "Новосибирск",
    }
    rows = []
    for key, label in labels.items():
        prefix = "✅ " if current == REGIONS[key] else ""
        rows.append([InlineKeyboardButton(text=prefix + label, callback_data=f"region:{key}")])
    rows.extend(
        [
            [InlineKeyboardButton(text="✍️ Другой город", callback_data="region:custom")],
            [InlineKeyboardButton(text="🌍 Любой регион", callback_data="region:all")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:root")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def discount_keyboard(current: Decimal) -> InlineKeyboardMarkup:
    values = (10, 15, 20, 25, 30)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current == Decimal(value) else ''}{value}%",
                    callback_data=f"discount:{value}",
                )
                for value in values[:3]
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current == Decimal(value) else ''}{value}%",
                    callback_data=f"discount:{value}",
                )
                for value in values[3:]
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:root")],
        ]
    )


def settings_text(preferences: UserPreferences) -> str:
    region = preferences.region.title() if preferences.region else "любой"
    state = "работают ✅" if preferences.enabled else "на паузе ⏸"
    return (
        "⚙️ <b>Настройки Avito Hunt</b>\n\n"
        f"Уведомления: <b>{state}</b>\n"
        f"Модели: <b>{format_models(preferences.model_generations)}</b>\n"
        f"Память: <b>{format_storage(preferences.storage_options)}</b>\n"
        f"Регион: <b>{region}</b>\n"
        f"Минимальная скидка: <b>{format_discount(preferences.min_discount_percent)}</b>\n\n"
        "По умолчанию я проверяю все модели iPhone — так вы не пропустите неожиданно "
        "выгодное предложение. При желании поиск можно сузить."
    )


def help_text() -> str:
    return (
        "❓ <b>Как работает Avito Hunt</b>\n\n"
        "Бот сравнивает новый iPhone с похожими объявлениями той же модели, памяти, "
        "состояния и региона. Если цена ниже выбранного порога, вы получаете уведомление.\n\n"
        "Низкая цена не гарантирует исправность устройства — проверяйте товар и не "
        "переводите предоплату."
    )


def back_keyboard(callback_data: str = "panel:root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data=callback_data)]]
    )


async def get_preferences(message: Message) -> UserPreferences:
    assert message.from_user
    preferences = await database.get_user_preferences(message.chat.id)
    if preferences:
        return preferences
    await database.register_user(message.chat.id, message.from_user.username)
    created = await database.get_user_preferences(message.chat.id)
    assert created
    return created


async def send_panel(
    message: Message,
    preferences: UserPreferences,
    *,
    text: str | None = None,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    await message.answer(
        text or panel_text(preferences),
        parse_mode="HTML",
        reply_markup=markup or panel_keyboard(preferences.enabled),
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    assert message.from_user
    await database.register_user(message.chat.id, message.from_user.username)
    preferences = await database.get_user_preferences(message.chat.id)
    assert preferences
    await send_panel(message, preferences)


@router.message(Command("stop"))
@router.message(F.text == "⏸ Пауза")
async def pause(message: Message) -> None:
    await get_preferences(message)
    await database.disable_user(message.chat.id)
    preferences = await database.get_user_preferences(message.chat.id)
    assert preferences
    await send_panel(message, preferences)


@router.message(Command("resume"))
@router.message(F.text == "▶️ Продолжить")
async def resume(message: Message) -> None:
    await get_preferences(message)
    await database.enable_user(message.chat.id)
    preferences = await database.get_user_preferences(message.chat.id)
    assert preferences
    await send_panel(message, preferences)


@router.message(Command("status"))
@router.message(F.text == "📊 Статус")
async def status(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(
        message,
        preferences,
        text="📊 <b>Текущий статус</b>\n\n" + settings_text(preferences),
        markup=back_keyboard(),
    )


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(
        message,
        preferences,
        text=settings_text(preferences),
        markup=settings_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(message, preferences, text=help_text(), markup=back_keyboard())


async def edit_callback(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error):
                raise


@router.callback_query(F.data == "panel:root")
async def panel_root(callback: CallbackQuery) -> None:
    waiting_for_region.pop(callback.from_user.id, None)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(callback, panel_text(preferences), panel_keyboard(preferences.enabled))


@router.callback_query(F.data == "panel:pause")
async def panel_pause(callback: CallbackQuery) -> None:
    await database.disable_user(callback.from_user.id)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(callback, panel_text(preferences), panel_keyboard(False))


@router.callback_query(F.data == "panel:resume")
async def panel_resume(callback: CallbackQuery) -> None:
    await database.enable_user(callback.from_user.id)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(callback, panel_text(preferences), panel_keyboard(True))


@router.callback_query(F.data == "panel:status")
async def panel_status(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            "📊 <b>Текущий статус</b>\n\n" + settings_text(preferences),
            back_keyboard(),
        )


@router.callback_query(F.data == "panel:help")
async def panel_help(callback: CallbackQuery) -> None:
    await edit_callback(
        callback,
        help_text(),
        back_keyboard(),
    )


@router.callback_query(F.data == "settings:root")
async def settings_root(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(callback, settings_text(preferences), settings_keyboard())


@router.callback_query(F.data == "settings:models")
async def settings_models(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            "📱 <b>Какие поколения отслеживать?</b>\n\n"
            "Сейчас: " + format_models(preferences.model_generations),
            models_keyboard(preferences.model_generations),
        )


@router.callback_query(F.data.startswith("model:"))
async def update_models(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not callback.data:
        return
    value = callback.data.split(":", 1)[1]
    selected = set(preferences.model_generations)
    if value == "all":
        selected.clear()
    elif value in selected:
        selected.remove(value)
    else:
        selected.add(value)
    ordered = tuple(value for value in MODEL_GENERATIONS if value in selected)
    await database.set_model_generations(callback.from_user.id, ordered)
    await edit_callback(
        callback,
        "📱 <b>Какие поколения отслеживать?</b>\n\nСейчас: " + format_models(ordered),
        models_keyboard(ordered),
    )


@router.callback_query(F.data == "settings:storage")
async def settings_storage(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            "💾 <b>Какой объём памяти отслеживать?</b>\n\n"
            "Сейчас: " + format_storage(preferences.storage_options),
            storage_keyboard(preferences.storage_options),
        )


@router.callback_query(F.data.startswith("storage:"))
async def update_storage(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not callback.data:
        return
    value = callback.data.split(":", 1)[1]
    selected = set(preferences.storage_options)
    if value == "all":
        selected.clear()
    else:
        numeric = int(value)
        if numeric in selected:
            selected.remove(numeric)
        else:
            selected.add(numeric)
    ordered = tuple(value for value in STORAGE_OPTIONS if value in selected)
    await database.set_storage_options(callback.from_user.id, ordered)
    await edit_callback(
        callback,
        "💾 <b>Какой объём памяти отслеживать?</b>\n\nСейчас: " + format_storage(ordered),
        storage_keyboard(ordered),
    )


@router.callback_query(F.data == "settings:region")
async def settings_region(callback: CallbackQuery) -> None:
    waiting_for_region.pop(callback.from_user.id, None)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        current = preferences.region.title() if preferences.region else "любой"
        await edit_callback(
            callback,
            f"📍 <b>В каком регионе искать?</b>\n\nСейчас: {current}",
            region_keyboard(preferences.region),
        )


@router.callback_query(F.data.startswith("region:"))
async def update_region(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        if isinstance(callback.message, Message):
            waiting_for_region[callback.from_user.id] = callback.message.message_id
        await edit_callback(
            callback,
            "✍️ <b>Другой город</b>\n\nНапишите название города одним сообщением.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Назад", callback_data="region:cancel")]
                ]
            ),
        )
        return
    if value == "cancel":
        waiting_for_region.pop(callback.from_user.id, None)
        preferences = await database.get_user_preferences(callback.from_user.id)
        if preferences:
            current = preferences.region.title() if preferences.region else "любой"
            await edit_callback(
                callback,
                f"📍 <b>В каком регионе искать?</b>\n\nСейчас: {current}",
                region_keyboard(preferences.region),
            )
        return
    region = None if value == "all" else REGIONS.get(value)
    await database.set_region(callback.from_user.id, region)
    current = region.title() if region else "любой"
    await edit_callback(
        callback,
        f"📍 <b>В каком регионе искать?</b>\n\nСейчас: {current}",
        region_keyboard(region),
    )


def is_waiting_for_region(message: Message) -> bool:
    return message.chat.id in waiting_for_region


@router.message(is_waiting_for_region)
async def custom_region(message: Message) -> None:
    value = (message.text or "").strip()
    panel_message_id = waiting_for_region[message.chat.id]
    if not 2 <= len(value) <= 80:
        await message.bot.edit_message_text(
            "⚠️ Название должно содержать от 2 до 80 символов.\n\nНапишите город ещё раз.",
            chat_id=message.chat.id,
            message_id=panel_message_id,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Назад", callback_data="region:cancel")]
                ]
            ),
        )
        return
    waiting_for_region.pop(message.chat.id, None)
    await database.set_region(message.chat.id, value)
    await message.bot.edit_message_text(
        f"📍 <b>В каком регионе искать?</b>\n\nСейчас: {value.title()} ✅",
        chat_id=message.chat.id,
        message_id=panel_message_id,
        parse_mode="HTML",
        reply_markup=region_keyboard(value.casefold()),
    )
    with suppress(TelegramBadRequest):
        await message.delete()


@router.callback_query(F.data == "settings:discount")
async def settings_discount(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            "📉 <b>При какой скидке уведомлять?</b>\n\n"
            f"Сейчас: {format_discount(preferences.min_discount_percent)}",
            discount_keyboard(preferences.min_discount_percent),
        )


@router.callback_query(F.data.startswith("discount:"))
async def update_discount(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    value = Decimal(callback.data.split(":", 1)[1])
    await database.set_min_discount(callback.from_user.id, value)
    await edit_callback(
        callback,
        f"📉 <b>При какой скидке уведомлять?</b>\n\nСейчас: {format_discount(value)}",
        discount_keyboard(value),
    )


@router.callback_query(F.data == "settings:close")
async def settings_close(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(callback, panel_text(preferences), panel_keyboard(preferences.enabled))


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
