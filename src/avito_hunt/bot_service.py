import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

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
from avito_hunt.importer import parse_import
from avito_hunt.logging import configure_logging
from avito_hunt.market_lab import format_lab_report, run_market_lab
from avito_hunt.messages import deal_message
from avito_hunt.preferences import (
    MODEL_GENERATIONS,
    STORAGE_OPTIONS,
    format_discount,
    format_models,
    format_storage,
)
from avito_hunt.provider import BatchSource
from avito_hunt.simulator import demo_estimate
from avito_hunt.worker_service import process_once

logger = logging.getLogger(__name__)
router = Router()
database: Database
waiting_for_region: dict[int, int] = {}
waiting_for_import: dict[int, int] = {}

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


def panel_keyboard(enabled: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Приостановить" if enabled else "▶️ Продолжить"
    toggle_data = "panel:pause" if enabled else "panel:resume"
    rows = [
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:root")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton(text="📊 Статус", callback_data="panel:status")],
        [InlineKeyboardButton(text="🧪 Демонстрация", callback_data="panel:demo")],
        [InlineKeyboardButton(text="👥 Пригласить", callback_data="panel:invite")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="panel:help")],
    ]
    if is_admin:
        rows.insert(-1, [InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Модели iPhone", callback_data="settings:models")],
            [InlineKeyboardButton(text="💾 Объём памяти", callback_data="settings:storage")],
            [InlineKeyboardButton(text="📍 Регион", callback_data="settings:region")],
            [InlineKeyboardButton(text="📉 Минимальная скидка", callback_data="settings:discount")],
            [InlineKeyboardButton(text="🌙 Тихие часы", callback_data="settings:quiet")],
            [InlineKeyboardButton(text="🔔 Лимит в день", callback_data="settings:limit")],
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


def quiet_keyboard(start: int | None, end: int | None) -> InlineKeyboardMarkup:
    values = (
        ("off", None, None, "Выключены"),
        ("23-8", 23, 8, "23:00–08:00"),
        ("22-9", 22, 9, "22:00–09:00"),
        ("0-8", 0, 8, "00:00–08:00"),
    )
    rows = []
    for key, option_start, option_end, label in values:
        selected = start == option_start and end == option_end
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if selected else ''}{label}",
                    callback_data=f"quiet:{key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="settings:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def limit_keyboard(current: int) -> InlineKeyboardMarkup:
    values = ((5, "5"), (10, "10"), (20, "20"), (50, "50"), (0, "Без лимита"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current == value else ''}{label}",
                    callback_data=f"limit:{value}",
                )
                for value, label in values[:3]
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current == value else ''}{label}",
                    callback_data=f"limit:{value}",
                )
                for value, label in values[3:]
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:root")],
        ]
    )


def settings_text(preferences: UserPreferences) -> str:
    region = preferences.region.title() if preferences.region else "любой"
    state = "работают ✅" if preferences.enabled else "на паузе ⏸"
    quiet = (
        "выключены"
        if preferences.quiet_start_hour is None
        else f"{preferences.quiet_start_hour:02d}:00–{preferences.quiet_end_hour:02d}:00 МСК"
    )
    limit = (
        "без лимита" if preferences.daily_alert_limit == 0 else str(preferences.daily_alert_limit)
    )
    return (
        "⚙️ <b>Настройки Avito Hunt</b>\n\n"
        f"Уведомления: <b>{state}</b>\n"
        f"Модели: <b>{format_models(preferences.model_generations)}</b>\n"
        f"Память: <b>{format_storage(preferences.storage_options)}</b>\n"
        f"Регион: <b>{region}</b>\n"
        f"Минимальная скидка: <b>{format_discount(preferences.min_discount_percent)}</b>\n\n"
        f"Тихие часы: <b>{quiet}</b>\n"
        f"Лимит уведомлений: <b>{limit} в день</b>\n\n"
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
        reply_markup=markup or panel_keyboard(preferences.enabled, preferences.is_admin),
    )


def onboarding_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать охоту", callback_data="onboarding:start")],
            [InlineKeyboardButton(text="🔒 Конфиденциальность", callback_data="legal:privacy")],
        ]
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    assert message.from_user
    parts = (message.text or "").split(maxsplit=1)
    referral_code = parts[1].strip() if len(parts) == 2 else None
    await database.register_user(
        message.chat.id,
        message.from_user.username,
        referral_code,
    )
    preferences = await database.get_user_preferences(message.chat.id)
    assert preferences
    if not preferences.onboarding_completed:
        await message.answer(
            "🏹 <b>Добро пожаловать в Avito Hunt</b>\n\n"
            "Я сам оцениваю рынок iPhone по модели, памяти, состоянию и региону. "
            "Если новое объявление заметно дешевле медианы, вы получите объяснимое "
            "уведомление с оценкой риска.\n\n"
            "По умолчанию включены все модели, любой регион и скидка от 15%.",
            parse_mode="HTML",
            reply_markup=onboarding_keyboard(),
        )
        return
    await send_panel(message, preferences)


@router.callback_query(F.data == "onboarding:start")
async def finish_onboarding(callback: CallbackQuery) -> None:
    await database.complete_onboarding(callback.from_user.id)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            panel_text(preferences),
            panel_keyboard(preferences.enabled, preferences.is_admin),
        )


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


@router.message(Command("demo"))
async def demo_command(message: Message) -> None:
    preferences = await get_preferences(message)
    listing, estimate = demo_estimate()
    await send_panel(
        message,
        preferences,
        text=deal_message(listing, estimate, demo=True),
        markup=back_keyboard(),
    )


@router.message(Command("privacy"))
async def privacy_command(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(message, preferences, text=privacy_text(), markup=back_keyboard())


@router.message(Command("terms"))
async def terms_command(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(message, preferences, text=terms_text(), markup=back_keyboard())


@router.message(Command("delete_me"))
async def delete_me_command(message: Message) -> None:
    preferences = await get_preferences(message)
    await send_panel(
        message,
        preferences,
        text="⚠️ <b>Удалить данные?</b>\n\nНастройки, история уведомлений и отзывы будут удалены.",
        markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Удалить навсегда", callback_data="account:delete")],
                [InlineKeyboardButton(text="← Отмена", callback_data="panel:root")],
            ]
        ),
    )


@router.callback_query(F.data == "account:delete")
async def delete_account(callback: CallbackQuery) -> None:
    await database.delete_user(callback.from_user.id)
    await edit_callback(
        callback,
        "Ваши пользовательские данные удалены. Чтобы начать заново, отправьте /start.",
        InlineKeyboardMarkup(inline_keyboard=[]),
    )


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
    waiting_for_import.pop(callback.from_user.id, None)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            panel_text(preferences),
            panel_keyboard(preferences.enabled, preferences.is_admin),
        )


@router.callback_query(F.data == "panel:pause")
async def panel_pause(callback: CallbackQuery) -> None:
    await database.disable_user(callback.from_user.id)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback, panel_text(preferences), panel_keyboard(False, preferences.is_admin)
        )


@router.callback_query(F.data == "panel:resume")
async def panel_resume(callback: CallbackQuery) -> None:
    await database.enable_user(callback.from_user.id)
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback, panel_text(preferences), panel_keyboard(True, preferences.is_admin)
        )


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


@router.callback_query(F.data == "panel:demo")
async def panel_demo(callback: CallbackQuery) -> None:
    listing, estimate = demo_estimate()
    await edit_callback(
        callback,
        deal_message(listing, estimate, demo=True),
        back_keyboard(),
    )


@router.callback_query(F.data == "panel:invite")
async def panel_invite(callback: CallbackQuery) -> None:
    code = await database.invite_code(callback.from_user.id)
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"
    await edit_callback(
        callback,
        "👥 <b>Приглашение в закрытый тест</b>\n\n"
        "Отправьте другу персональную ссылку:\n"
        f"<code>{link}</code>\n\n"
        "Код нужен только для учёта первых тестировщиков.",
        back_keyboard(),
    )


def privacy_text() -> str:
    return (
        "🔒 <b>Конфиденциальность</b>\n\n"
        "Бот хранит Telegram ID, имя пользователя, настройки поиска, историю "
        "отправленных уведомлений и ваши оценки предложений. Токены, переписка с "
        "продавцами и платёжные данные не собираются.\n\n"
        "Для удаления данных напишите /delete_me."
    )


def terms_text() -> str:
    return (
        "📄 <b>Условия использования</b>\n\n"
        "Avito Hunt предоставляет аналитическую оценку, а не гарантию подлинности, "
        "исправности или выгодности товара. Пользователь самостоятельно проверяет "
        "продавца и устройство. Бот не участвует в оплате и сделке."
    )


@router.callback_query(F.data == "legal:privacy")
async def legal_privacy(callback: CallbackQuery) -> None:
    await edit_callback(callback, privacy_text(), back_keyboard())


@router.callback_query(F.data.startswith("feedback:"))
async def listing_feedback(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    _, verdict, key = callback.data.split(":", 2)
    result = await database.learn_from_feedback(callback.from_user.id, key, verdict)
    if not result.saved:
        await callback.answer("Объявление не найдено")
    elif result.duplicate:
        await callback.answer("Этот отзыв уже учтён ✅")
    elif not result.learned:
        await callback.answer("Отзыв сохранён; обучение включено для новых карточек ✅")
    else:
        await callback.answer(f"Спасибо! Модель обучена на {result.samples} отзывах ✅")


async def admin_text() -> str:
    stats = await database.admin_stats()
    source = stats["source"]
    source_status = source.get("status", "unknown") if isinstance(source, dict) else "unknown"
    source_details = ""
    if isinstance(source, dict):
        provider = source.get("provider")
        received = source.get("received")
        accepted = source.get("accepted")
        fetched_at = source.get("fetched_at")
        if provider:
            source_details += f"\nПоставщик: <b>{escape(str(provider))}</b>"
        if received is not None and accepted is not None:
            source_details += f"\nПоследний сбор: <b>{accepted}/{received}</b> карточек"
        if fetched_at:
            source_details += f"\nПолучено: <code>{escape(str(fetched_at))}</code>"
    return (
        "🛠 <b>Админ-панель Avito Hunt</b>\n\n"
        f"Пользователи: <b>{stats['users']}</b>\n"
        f"Активные: <b>{stats['enabled_users']}</b>\n"
        f"Объявления: <b>{stats['listings']}</b>\n"
        f"Уведомления: <b>{stats['notifications']}</b>\n"
        f"Отзывы: <b>{stats['feedback']}</b>\n"
        f"Обучающих оценок: <b>{stats['model_samples']}</b> "
        f"(🔥 {stats['model_positives']} / 😐 {stats['model_negatives']})\n"
        f"Источник: <b>{source_status}</b>{source_details}"
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Запустить Market Lab", callback_data="admin:lab")],
            [InlineKeyboardButton(text="📥 Импорт JSON/CSV", callback_data="admin:import")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:root")],
            [InlineKeyboardButton(text="← Назад", callback_data="panel:root")],
        ]
    )


@router.callback_query(F.data == "admin:root")
async def admin_root(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not preferences.is_admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await edit_callback(callback, await admin_text(), admin_keyboard())


@router.callback_query(F.data == "admin:lab")
async def admin_market_lab(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not preferences.is_admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    report = await asyncio.to_thread(run_market_lab)
    await edit_callback(callback, format_lab_report(report), back_keyboard("admin:root"))


@router.callback_query(F.data == "admin:import")
async def admin_import(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not preferences.is_admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if isinstance(callback.message, Message):
        waiting_for_import[callback.from_user.id] = callback.message.message_id
    await edit_callback(
        callback,
        "📥 <b>Импорт тестовых объявлений</b>\n\n"
        "Отправьте файл JSON или CSV размером до 1 МБ и не более 1000 записей. "
        "Объявления пройдут тот же фильтр, оценку рынка и дедупликацию, что и данные "
        "будущего поставщика. Подходящие предложения могут отправить уведомления "
        "активным тестировщикам.",
        back_keyboard("admin:import_cancel"),
    )


@router.callback_query(F.data == "admin:import_cancel")
async def admin_import_cancel(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if not preferences or not preferences.is_admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    waiting_for_import.pop(callback.from_user.id, None)
    await edit_callback(callback, await admin_text(), admin_keyboard())


def is_waiting_for_import(message: Message) -> bool:
    return message.chat.id in waiting_for_import and message.document is not None


@router.message(is_waiting_for_import)
async def receive_admin_import(message: Message) -> None:
    panel_message_id = waiting_for_import.pop(message.chat.id)
    preferences = await database.get_user_preferences(message.chat.id)
    if not preferences or not preferences.is_admin or not message.document:
        return
    markup = back_keyboard("admin:root")
    try:
        if message.document.file_size and message.document.file_size > 1_000_000:
            raise ValueError("Файл больше 1 МБ")
        filename = message.document.file_name or "import"
        buffer = BytesIO()
        await message.bot.download(message.document, destination=buffer)
        if buffer.getbuffer().nbytes > 1_000_000:
            raise ValueError("Файл больше 1 МБ")
        batch = await asyncio.to_thread(parse_import, buffer.getvalue(), filename)
        await process_once(
            database,
            BatchSource(batch),
            message.bot,
            update_source_state=False,
        )
        text = (
            "✅ <b>Импорт завершён</b>\n\n"
            f"Получено строк: <b>{batch.received_count}</b>\n"
            f"Принято iPhone: <b>{len(batch.listings)}</b>\n"
            f"Отклонено фильтрами: <b>{batch.rejected_count}</b>"
        )
    except (ValueError, UnicodeError) as error:
        text = f"⚠️ <b>Импорт не выполнен</b>\n\n{escape(str(error))}"
    except Exception:
        logger.exception("Admin listing import failed")
        text = "⚠️ <b>Импорт не выполнен</b>\n\nВнутренняя ошибка записана в журнал."
    await message.bot.edit_message_text(
        text,
        chat_id=message.chat.id,
        message_id=panel_message_id,
        parse_mode="HTML",
        reply_markup=markup,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


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


@router.callback_query(F.data == "settings:quiet")
async def settings_quiet(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        current = (
            "выключены"
            if preferences.quiet_start_hour is None
            else f"{preferences.quiet_start_hour:02d}:00–{preferences.quiet_end_hour:02d}:00 МСК"
        )
        await edit_callback(
            callback,
            f"🌙 <b>Тихие часы</b>\n\nСейчас: {current}\n"
            "В этот период новые уведомления не отправляются.",
            quiet_keyboard(preferences.quiet_start_hour, preferences.quiet_end_hour),
        )


@router.callback_query(F.data.startswith("quiet:"))
async def update_quiet(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    value = callback.data.split(":", 1)[1]
    options = {"off": (None, None), "23-8": (23, 8), "22-9": (22, 9), "0-8": (0, 8)}
    start_hour, end_hour = options[value]
    await database.set_quiet_hours(callback.from_user.id, start_hour, end_hour)
    current = "выключены" if start_hour is None else f"{start_hour:02d}:00–{end_hour:02d}:00 МСК"
    await edit_callback(
        callback,
        f"🌙 <b>Тихие часы</b>\n\nСейчас: {current}",
        quiet_keyboard(start_hour, end_hour),
    )


@router.callback_query(F.data == "settings:limit")
async def settings_limit(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        current = (
            "без лимита"
            if preferences.daily_alert_limit == 0
            else f"{preferences.daily_alert_limit} в день"
        )
        await edit_callback(
            callback,
            f"🔔 <b>Лимит уведомлений</b>\n\nСейчас: {current}",
            limit_keyboard(preferences.daily_alert_limit),
        )


@router.callback_query(F.data.startswith("limit:"))
async def update_limit(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    value = int(callback.data.split(":", 1)[1])
    await database.set_daily_alert_limit(callback.from_user.id, value)
    current = "без лимита" if value == 0 else f"{value} в день"
    await edit_callback(
        callback,
        f"🔔 <b>Лимит уведомлений</b>\n\nСейчас: {current}",
        limit_keyboard(value),
    )


@router.callback_query(F.data == "settings:close")
async def settings_close(callback: CallbackQuery) -> None:
    preferences = await database.get_user_preferences(callback.from_user.id)
    if preferences:
        await edit_callback(
            callback,
            panel_text(preferences),
            panel_keyboard(preferences.enabled, preferences.is_admin),
        )


async def daily_admin_report_loop(bot: Bot) -> None:
    while True:
        try:
            now = datetime.now(ZoneInfo("Europe/Moscow"))
            state = await database.get_system_state("daily_admin_report") or {}
            if now.hour == 9 and state.get("date") != now.date().isoformat():
                deleted = await database.cleanup_expired_data()
                text = "☀️ <b>Ежедневная сводка</b>\n\n" + await admin_text()
                for chat_id in await database.admin_chat_ids():
                    await bot.send_message(chat_id, text, parse_mode="HTML")
                await database.set_system_state(
                    "daily_admin_report",
                    {"date": now.date().isoformat(), "retention_cleanup": deleted},
                )
        except Exception:
            logger.exception("Daily admin report failed")
        await asyncio.sleep(300)


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
    report_task = asyncio.create_task(daily_admin_report_loop(bot))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        logger.info("Starting Telegram long polling")
        await dispatcher.start_polling(bot)
    finally:
        report_task.cancel()
        with suppress(asyncio.CancelledError):
            await report_task
        await bot.session.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
