import re

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramMigrateToChat
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import json
from io import BytesIO
from core.callbacks import CallbackData
from core.config import settings
from core.curator_const import is_responsible_user
from core.resources.text_file.texts import MESSAGES
from keyboards import inline as ikb
from keyboards import reply as rkb
from services.access_control import is_admin
from services.registration_store import get_approved_user
from services.fsm_scope import reset_user_wizard_for_main_menu
from services.status import build_applicant_status_text, build_moderation_queue_text
from services.support_tickets import (
    assign_ticket,
    append_staff_payload,
    build_staff_performance,
    append_user_payload,
    block_actor_by_ticket,
    unblock_actor_by_ticket,
    unblock_actor_by_key,
    close_ticket,
    get_ticket,
    get_ticket_by_chat_message,
    is_actor_blocked,
    link_chat_message,
    open_or_get_ticket,
    list_blocked_actors,
    list_staff_registry,
    register_staff_profile,
    set_ticket_assignees,
    set_ticket_rating,
    set_ticket_rating_comment,
    ticket_message_refs,
    tickets_by_alias,
    format_staff_stats,
)
from services.support_transport import build_message_payload, copy_with_reply, is_ticket_message_supported
from services.user_data import build_user_data_export, delete_user_data
from states.states import HelpRequest
from utils.i18n import tr
from utils.main_menu_reply import sync_main_menu_reply_keyboard
from utils.validators import MIN_HELP_TEXT_LEN, MIN_RATING_COMMENT_LEN, validate_min_plaintext

router = Router()
async def _can_manage_support(from_user_id: int) -> bool:
    return bool(await is_admin(from_user_id) or await is_responsible_user(from_user_id))


def _staff_label(staff_id: int, profile: dict[str, str]) -> str:
    username = str((profile or {}).get("username", "")).strip()
    full_name = str((profile or {}).get("full_name", "")).strip()
    if username and full_name:
        return f"{full_name} (@{username})"
    if username:
        return f"@{username}"
    return full_name or f"ID {staff_id}"


def _format_assignees(ticket: dict[str, object]) -> str:
    raw = ticket.get("assigned_staff_ids") or []
    ids: list[int] = []
    if isinstance(raw, list):
        for x in raw:
            try:
                ids.append(int(x))
            except Exception:
                continue
    else:
        try:
            ids = [int(ticket.get("assigned_staff_id") or 0)]
        except Exception:
            ids = []
    ids = [x for x in ids if x > 0]
    if not ids:
        return "не назначены"
    profiles = ticket.get("staff_profiles") or {}
    labels: list[str] = []
    for sid in ids:
        profile = {}
        if isinstance(profiles, dict):
            profile = profiles.get(str(sid), {}) or {}
        labels.append(_staff_label(int(sid), profile))
    return ", ".join(labels)


async def _render_assign_kb(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    ticket_id: str,
    rows: list[tuple[int, dict[str, str]]],
    selected: set[int],
    header: str | None = None,
) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for staff_id, profile in rows[:25]:
        mark = "✅ " if int(staff_id) in selected else ""
        builder.row(
            types.InlineKeyboardButton(
                text=f"{mark}{_staff_label(int(staff_id), profile)}",
                callback_data=f"{CallbackData.SUPPORT_ASSIGN_PICK_PREFIX}{ticket_id}_{int(staff_id)}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text="✅ Готово",
            callback_data=f"{CallbackData.SUPPORT_ASSIGN_APPLY_PREFIX}{ticket_id}",
        )
    )
    text = header or f"Выберите психологов для тикета #{ticket_id} (можно несколько):"
    await bot.edit_message_text(
        chat_id=int(chat_id),
        message_id=int(message_id),
        text=text,
        reply_markup=builder.as_markup(),
    )


async def _is_psy_admin(user_id: int) -> bool:
    return bool(await is_admin(user_id) or (settings.psycholog_admin_id is not None and int(user_id) == int(settings.psycholog_admin_id)))


def _configured_support_chat_ids() -> set[int]:
    chat_ids: set[int] = {int(settings.moderation_chat_id)}
    if settings.psycholog_chat_id is not None:
        chat_ids.add(int(settings.psycholog_chat_id))
    return chat_ids



def _support_target_chat(topic_code: str) -> int | None:
    if topic_code == "psy":
        return settings.psycholog_chat_id
    if topic_code == "uni":
        return settings.moderation_chat_id
    return None


def _ticket_id_from_text(text: str) -> str:
    """Пытается извлечь ID тикета из текста служебного сообщения."""
    raw = str(text or "")
    match = re.search(r"#ticket_(\d+)", raw)
    if match:
        return match.group(1)
    match = re.search(r"Тикет\s*#(\d+)", raw)
    if match:
        return match.group(1)
    return ""


def _ticket_search_tags(ticket: dict) -> tuple[str, str]:
    ticket_tag = f"#ticket_{ticket['ticket_id']}"
    if ticket.get("anonymous"):
        actor_tag = f"#anon_{ticket['anonymous_id']}"
    else:
        actor_tag = f"#user_{ticket['user_id']}"
    return ticket_tag, actor_tag


def _normalize_ticket_id(raw: str) -> str:
    value = str(raw or "").strip()
    if value.startswith("#ticket_"):
        return value.replace("#ticket_", "", 1)
    if value.startswith("ticket_"):
        return value.replace("ticket_", "", 1)
    if value.startswith("#"):
        return value[1:]
    if not value.isdigit():
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return digits
    return value


async def _resolve_existing_ticket_id(raw: str) -> str:
    """Надежно резолвит ticket_id для разных форматов (legacy + prefixed)."""
    candidates: list[str] = []
    source = str(raw or "").strip()
    normalized = _normalize_ticket_id(source)
    for item in (source, normalized):
        if item and item not in candidates:
            candidates.append(item)
    if normalized:
        prefixed = f"ticket_{normalized}"
        hash_prefixed = f"#ticket_{normalized}"
        if prefixed not in candidates:
            candidates.append(prefixed)
        if hash_prefixed not in candidates:
            candidates.append(hash_prefixed)
    for candidate in candidates:
        found = await get_ticket(candidate)
        if found:
            # Всегда возвращаем канонический ID из стора (обычно чистые цифры),
            # чтобы не размножать форматы вроде apply_10014 / ticket_10014.
            return str(found.get("ticket_id") or normalized)
    return normalized


def _help_back_callback(state_data: dict) -> str:
    return CallbackData.LEVEL_COLL if state_data.get("admission_track") == "college" or state_data.get("current_choice") == "Колледж" else CallbackData.LEVEL_UNI


def _is_college_context(state_data: dict) -> bool:
    return state_data.get("admission_track") == "college" or state_data.get("current_choice") == "Колледж"


async def _send_to_support_chat_with_migration(
    bot: Bot,
    target_chat_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
) -> tuple[types.Message, int]:
    try:
        sent = await bot.send_message(target_chat_id, text, reply_markup=reply_markup)
        return sent, int(target_chat_id)
    except TelegramMigrateToChat as err:
        migrated_chat_id = int(err.migrate_to_chat_id)
        sent = await bot.send_message(migrated_chat_id, text, reply_markup=reply_markup)
        return sent, migrated_chat_id

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Точка входа: сброс состояний и выбор языка."""
    await state.clear()
    await state.update_data(action_kb_initialized=False)
    await message.answer(
        "Выберите язык! / Тілді таңдаңыз!", 
        reply_markup=ikb.get_lang_kb(),
    )

@router.callback_query(F.data == CallbackData.START)
async def back_to_start(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору языка."""
    await state.clear()
    await state.update_data(action_kb_initialized=False)
    await callback.message.edit_text(
        "Выберите язык! / Тілді таңдаңыз!", 
        reply_markup=ikb.get_lang_kb()
    )
    await callback.answer()

@router.callback_query(F.data.startswith(CallbackData.LANG_PREFIX))
async def select_level(callback: types.CallbackQuery, state: FSMContext):
    """Сохранение языка и выбор уровня обучения."""
    lang = callback.data.split("_")[1]
    await state.update_data(locale=lang)
    
    text = MESSAGES[lang]["select_level"]
    await callback.message.edit_text(
        text, 
        reply_markup=ikb.get_level_kb(lang)
    )
    await callback.answer()

@router.callback_query(F.data == CallbackData.LEVEL_UNI)
async def uni_menu(callback: types.CallbackQuery, state: FSMContext):
    """Главное меню Университета."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await reset_user_wizard_for_main_menu(state)
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(current_choice="Университет", admission_track="uni")

    text = MESSAGES[lang]["main_menu"]
    approved_profile = await get_approved_user(callback.from_user.id)
    reviewer = await is_responsible_user(callback.from_user.id)
    admin = await is_admin(callback.from_user.id)
    from utils.safe_telegram import edit_or_send_text

    await edit_or_send_text(
        callback.message,
        text,
        reply_markup=ikb.get_uni_menu(
            lang,
            is_registered=approved_profile is not None,
            is_responsible=reviewer,
        ),
    )
    await sync_main_menu_reply_keyboard(
        callback.bot,
        chat_id=callback.message.chat.id,
        lang=lang,
        reply_markup=rkb.get_main_action_kb(
            lang,
            is_registered=approved_profile is not None,
            is_reviewer=reviewer,
            is_admin=admin,
            is_psy_admin=await _is_psy_admin(callback.from_user.id),
        ),
        state=state,
    )
    await callback.answer()


@router.message(F.text.in_(["🏠 Главное меню", "🏠 Басты мәзір"]))
async def main_menu_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    is_college = data.get("admission_track") == "college" or data.get("current_choice") == "Колледж"
    await reset_user_wizard_for_main_menu(state)
    data = await state.get_data()
    lang = data.get("locale", "ru")
    approved_profile = await get_approved_user(message.from_user.id)
    reviewer = await is_responsible_user(message.from_user.id)
    admin = await is_admin(message.from_user.id)
    await message.answer(
        MESSAGES[lang]["college_menu"] if is_college else MESSAGES[lang]["main_menu"],
        reply_markup=ikb.get_college_menu(lang) if is_college else ikb.get_uni_menu(lang),
    )
    await sync_main_menu_reply_keyboard(
        message.bot,
        chat_id=message.chat.id,
        lang=lang,
        reply_markup=rkb.get_main_action_kb(
            lang,
            is_registered=approved_profile is not None,
            is_reviewer=reviewer,
            is_admin=admin,
            is_psy_admin=await _is_psy_admin(message.from_user.id),
        ),
        state=state,
    )


@router.message(F.text.in_(["🎓 Выбор уровня", "🎓 Деңгей таңдау"]))
async def choose_level_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await message.answer(
        MESSAGES[lang]["select_level"],
        reply_markup=ikb.get_level_kb(lang),
    )


@router.message(F.text.in_(["🆘 Помощь", "🆘 Көмек"]))
async def help_menu_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    title = (
        tr(
            lang,
            "Выберите раздел помощи. Для связи нажмите нужную кнопку:",
            "Көмек бөлімін таңдаңыз. Байланысу үшін қажетті батырманы басыңыз:",
        )
    )
    await message.answer(
        title,
        reply_markup=ikb.get_help_menu_kb(
            lang,
            back_callback=_help_back_callback(data),
            track="college" if _is_college_context(data) else "uni",
        ),
    )


@router.callback_query(F.data.startswith(CallbackData.HELP_PREFIX))
async def help_option(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    code = callback.data.replace(CallbackData.HELP_PREFIX, "")
    is_college = _is_college_context(data)
    labels = {
        "ru": {
            "tech": "Техническая поддержка",
            "psy": "Психологическая поддержка",
            "uni": "Вопрос колледжу" if is_college else "Вопрос университету",
            "book": "Книга жалоб и предложений",
        },
        "kz": {
            "tech": "Техникалық қолдау",
            "psy": "Психологиялық қолдау",
            "uni": "Колледжге сұрақ" if is_college else "Университетке сұрақ",
            "book": "Шағымдар мен ұсыныстар кітабы",
        },
    }
    selected = labels.get(lang, labels["ru"]).get(code)
    if not selected:
        await callback.answer("Неизвестный раздел.", show_alert=True)
        return
    if code == "psy":
        ticket = await open_or_get_ticket(callback.from_user.id, "psy", anonymous=True)
        await state.update_data(psy_ticket_id=ticket["ticket_id"], support_ticket_id=ticket["ticket_id"], help_topic_code="psy")
        await state.set_state(HelpRequest.waiting_for_text)
        await callback.message.answer(
            tr(
                lang,
                f"🧠 Анонимный чат с психологом открыт.\n"
                f"Тикет #{ticket['ticket_id']}.\n"
                "Напишите сообщение в этот чат. Можно выйти в меню, тикет останется активным.",
                f"🧠 Психологпен аноним чат ашылды.\n"
                f"Тикет #{ticket['ticket_id']}.\n"
                "Осы чатқа хабарлама жазыңыз. Мәзірге шыға аласыз, тикет ашық қалады.",
            ),
            reply_markup=ikb.get_psy_ticket_kb(ticket["ticket_id"], lang, menu_callback=_help_back_callback(data)),
        )
        await callback.answer(tr(lang, "Психологический тикет открыт.", "Психологиялық тикет ашылды."))
        return
    if code == "uni":
        if is_college:
            from core.config import settings

            await callback.message.answer(
                tr(
                    lang,
                    "🏫 Вопрос колледжу — напишите в WhatsApp приёмной:",
                    "🏫 Колледжге сұрақ — WhatsApp арқылы жазыңыз:",
                ),
                reply_markup=ikb.get_college_whatsapp_kb(lang, back_callback=_help_back_callback(data)),
            )
            await callback.answer(tr(lang, "Откроется WhatsApp.", "WhatsApp ашылады."))
            return
        await callback.message.answer(
            tr(
                lang,
                "🎓 Для официальных обращений используйте блог ректора университета.",
                "🎓 Ресми өтініштер үшін университет ректорының блогын пайдаланыңыз.",
            ),
            reply_markup=ikb.get_rector_blog_kb(lang, back_callback=_help_back_callback(data)),
        )
        await callback.answer(tr(lang, "Ссылка открыта.", "Сілтеме дайын."))
        return
    await state.update_data(help_topic=selected, help_topic_code=code)
    await state.set_state(HelpRequest.waiting_for_text)
    await callback.message.answer(
        tr(
            lang,
            f"Опишите ваш запрос по разделу «{selected}» одним сообщением.",
            f"«{selected}» бөлімі бойынша сұрағыңызды бір хабарламада жазыңыз.",
        )
    )
    await callback.answer(tr(lang, "Раздел выбран.", "Бөлім таңдалды."))


@router.message(HelpRequest.waiting_for_text)
async def help_collect_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    text = (message.text or "").strip()
    if message.text and text.startswith("/"):
        return
    support_topic = str(data.get("help_topic_code", ""))
    support_ticket_id = str(data.get("support_ticket_id") or data.get("psy_ticket_id") or "")
    if support_topic in {"psy", "uni"} or support_ticket_id:
        if not is_ticket_message_supported(message):
            await message.answer("Этот тип сообщения пока не поддерживается для тикетов.")
            return
        if not support_ticket_id:
            ticket = await open_or_get_ticket(message.from_user.id, support_topic or "psy", anonymous=(support_topic != "uni"))
            support_ticket_id = str(ticket["ticket_id"])
        existing_ticket = await get_ticket(support_ticket_id)
        effective_topic = str(existing_ticket.get("topic_code")) if existing_ticket else (support_topic or "psy")
        is_anon = bool(existing_ticket.get("anonymous")) if existing_ticket else (effective_topic != "uni")
        blocked, blocked_until = await is_actor_blocked(
            message.from_user.id,
            effective_topic,
            anonymous=is_anon,
        )
        if blocked:
            await message.answer(
                f"Ваши обращения временно ограничены. Срок блокировки: {blocked_until}."
                if blocked_until
                else "Ваши обращения заблокированы."
            )
            return
        ticket_id = support_ticket_id
        payload = build_message_payload(message)
        ticket = await append_user_payload(ticket_id, payload)
        if not ticket:
            await message.answer("Не удалось сохранить сообщение. Попробуйте снова.")
            return
        target_chat_id = _support_target_chat(ticket.get("topic_code", ""))
        if not target_chat_id:
            await message.answer("Целевой чат поддержки не настроен. Обратитесь к администратору.")
            return
        ticket_tag, actor_tag = _ticket_search_tags(ticket)
        topic_title = "Психологическая поддержка" if ticket.get("topic_code") == "psy" else "Приемная комиссия"
        actor_title = f"Аноним: {actor_tag}" if ticket.get("anonymous") else f"Пользователь: {actor_tag}"
        staff_text = (
            f"Тикет: {ticket_tag}\n"
            f"{actor_title}\n\n"
            f"📨 Новое сообщение ({topic_title})\n\n"
            f"{payload.get('preview', '-')}"
        )
        sent, actual_chat_id = await _send_to_support_chat_with_migration(
            message.bot,
            int(target_chat_id),
            staff_text,
            ikb.get_psy_staff_ticket_kb(
                ticket["ticket_id"],
                ticket["anonymous_id"],
                anonymous=bool(ticket.get("anonymous")),
            ),
        )
        if int(actual_chat_id) != int(target_chat_id):
            env_key = "PSYCHOLOG_CHAT_ID" if ticket.get("topic_code") == "psy" else "REVIEW_CHAT_ID"
            await message.answer(f"Чат поддержки был мигрирован Telegram. Обновите {env_key} в .env на {actual_chat_id}")
        await link_chat_message(ticket["ticket_id"], sent.message_id, actual_chat_id)
        copied_id = await copy_with_reply(
            message.bot,
            to_chat_id=int(actual_chat_id),
            from_chat_id=int(message.chat.id),
            message_id=int(message.message_id),
            reply_to_message_id=int(sent.message_id),
        )
        if copied_id is not None:
            await link_chat_message(ticket["ticket_id"], copied_id, actual_chat_id)
        await message.answer(
            tr(
                lang,
                "✨ Сообщение отправлено психологам.\nОжидайте ответ.",
                "✨ Хабарлама психологтарға жіберілді.\nЖауап күтіңіз.",
            ),
            reply_markup=ikb.get_psy_ticket_kb(ticket["ticket_id"], lang, menu_callback=_help_back_callback(data)),
        )
        return

    if not validate_min_plaintext(text, min_len=MIN_HELP_TEXT_LEN):
        await message.answer(
            tr(
                lang,
                "Опишите проблему подробнее, минимум 5 символов.",
                "Мәселені толығырақ жазыңыз, кемінде 5 таңба.",
            )
        )
        return

    await state.update_data(help_text=text)
    await state.set_state(HelpRequest.waiting_for_confirm)
    await message.answer(
        tr(
            lang,
            "Проверьте обращение и подтвердите отправку.",
            "Өтінішті тексеріп, жіберуді растаңыз.",
        ),
        reply_markup=ikb.get_help_confirm_kb(lang),
    )


@router.callback_query(HelpRequest.waiting_for_confirm, F.data == CallbackData.HELP_CONFIRM)
async def help_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    topic = data.get("help_topic", "-")
    help_text = data.get("help_text", "-")
    user = callback.from_user
    username = f"@{user.username}" if user.username else "-"
    await callback.bot.send_message(
        chat_id=settings.admin_id,
        text=(
            "📩 Новое обращение из бота\n\n"
            f"Раздел: {topic}\n"
            f"Пользователь: {user.full_name}\n"
            f"ID: {user.id}\n"
            f"Username: {username}\n\n"
            f"Текст обращения:\n{help_text}"
        ),
    )
    await state.clear()
    await callback.message.edit_text(
        tr(
            lang,
            "✅ Обращение отправлено. Ожидайте обратной связи.",
            "✅ Өтініш жіберілді. Кері байланыс күтіңіз.",
        )
    )
    await callback.answer()


@router.callback_query(HelpRequest.waiting_for_confirm, F.data == CallbackData.HELP_RESET)
async def help_reset(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.clear()
    await callback.message.edit_text(
        tr(
            lang,
            "❌ Обращение сброшено. При необходимости начните заново через кнопку «Помощь».",
            "❌ Өтініш өшірілді. Қажет болса, «Көмек» батырмасы арқылы қайта бастаңыз.",
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.PSY_CLOSE_PREFIX))
async def psy_close_ticket(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = callback.data.replace(CallbackData.PSY_CLOSE_PREFIX, "")
    ticket = await get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(callback.from_user.id):
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    closed = await close_ticket(ticket_id, closed_by_user=True)
    await state.update_data(psy_ticket_id=None)
    await state.update_data(support_ticket_id=None)
    if closed:
        target_chat_id = _support_target_chat(str(closed.get("topic_code", "")))
        if target_chat_id:
            await callback.bot.send_message(
                int(target_chat_id),
                "✅ Тикет закрыт пользователем\n"
                f"Тикет: #ticket_{ticket_id}\n"
                f"Назначены: {_format_assignees(closed)}\n"
                f"Итоговая статистика ответов: {format_staff_stats(closed)}",
            )
    await callback.message.edit_text(
        "Тикет закрыт. Оцените качество поддержки от 1 до 10:",
        reply_markup=ikb.get_psy_rating_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.PSY_RATE_PREFIX))
async def psy_rate_ticket(callback: types.CallbackQuery, state: FSMContext):
    payload = callback.data.replace(CallbackData.PSY_RATE_PREFIX, "")
    ticket_id, _, rating_raw = payload.partition("_")
    if not rating_raw.isdigit():
        await callback.answer("Некорректная оценка.", show_alert=True)
        return
    rating = int(rating_raw)
    if rating < 1 or rating > 10:
        await callback.answer("Оценка должна быть от 1 до 10.", show_alert=True)
        return
    ticket = await get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(callback.from_user.id):
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    await set_ticket_rating(ticket_id, rating)
    await state.update_data(rating_ticket_id=ticket_id, rating_value=rating)
    await state.set_state(HelpRequest.waiting_for_rating_comment)
    await callback.message.edit_text("Спасибо! Теперь напишите комментарий к оценке ")
    await callback.answer()


@router.message(HelpRequest.waiting_for_rating_comment)
async def psy_rating_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = str(data.get("rating_ticket_id", ""))
    rating_value = int(data.get("rating_value", 0))
    ticket = await get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(message.from_user.id):
        await message.answer("Тикет не найден.")
        await state.clear()
        return
    comment = (message.text or "").strip()
    if not validate_min_plaintext(comment, min_len=MIN_RATING_COMMENT_LEN):
        await message.answer("Напишите комментарий чуть подробнее (минимум 3 символа).")
        return
    await set_ticket_rating_comment(ticket_id, comment)
    target_chat_id = _support_target_chat(str(ticket.get("topic_code", "")))
    if target_chat_id:
        feedback_text = (
            f"📝 Оценка по тикету #ticket_{ticket_id}\n"
            f"Оценка: {rating_value}/10\n"
            f"Комментарий: {comment}"
        )
        await message.bot.send_message(int(target_chat_id), feedback_text)
    await message.answer("Спасибо за подробную обратную связь.")
    await state.clear()


@router.callback_query(F.data.startswith(CallbackData.PSY_VIEW_TICKET_PREFIX))
async def psy_view_ticket(callback: types.CallbackQuery):
    ticket_id = callback.data.replace(CallbackData.PSY_VIEW_TICKET_PREFIX, "")
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    lines = [
        f"Тикет #{ticket_id}",
        f"Аноним #{ticket.get('anonymous_id')}",
        f"Статус: {ticket.get('status')}",
        f"Сообщений: {len(ticket.get('messages', []))}",
        "Последние сообщения:",
    ]
    for row in ticket.get("messages", [])[-8:]:
        prefix = "👤" if row.get("from") == "user" else "🧑‍⚕️"
        lines.append(f"{prefix} {row.get('text', '-')}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.PSY_VIEW_ALIAS_PREFIX))
async def psy_view_alias(callback: types.CallbackQuery):
    alias = callback.data.replace(CallbackData.PSY_VIEW_ALIAS_PREFIX, "")
    rows = await tickets_by_alias(alias)
    if not rows:
        await callback.answer("Обращений не найдено.", show_alert=True)
        return
    is_anonymous = bool(rows[0].get("anonymous")) if rows else True
    actor_title = "Аноним" if is_anonymous else "Пользователь"
    lines = [f"{actor_title} #{alias}. Всего обращений: {len(rows)}"]
    for row in rows[:10]:
        lines.append(f"• Тикет #{row.get('ticket_id')} | {row.get('topic_code')} | {row.get('status')}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(
    lambda callback: bool(getattr(callback, "data", ""))
    and str(callback.data).startswith(CallbackData.SUPPORT_BLOCK_PREFIX)
    and not str(callback.data).startswith(CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX)
)
async def support_block_prompt(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_BLOCK_PREFIX, "")
    ticket_id, _, mode = payload.partition("_")
    ticket = await get_ticket(ticket_id) or await get_ticket(_ticket_id_from_text(str(getattr(callback.message, "text", "") or "")))
    if not ticket or ticket.get("topic_code") != "psy":
        await callback.answer("Блокировка доступна только для психологических тикетов.", show_alert=True)
        return
    mode_label = "24 часа" if mode == "24h" else "навсегда"
    try:
        await callback.message.edit_text(
            f"Подтвердите блокировку пользователя по тикету #{ticket_id} ({mode_label}).",
            reply_markup=ikb.get_support_confirm_kb("block", payload),
        )
    except Exception:
        await callback.message.answer(
            f"Подтвердите блокировку пользователя по тикету #{ticket_id} ({mode_label}).",
            reply_markup=ikb.get_support_confirm_kb("block", payload),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX))
async def support_block_confirm(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX, "")
    decision, _, rest = payload.partition("_")
    if decision != "yes":
        await callback.answer("Отменено.")
        return
    ticket_id, _, mode = rest.partition("_")
    ticket = await block_actor_by_ticket(ticket_id, mode, callback.from_user.id)
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    try:
        await callback.message.edit_text(f"Пользователь по тикету #{ticket_id} заблокирован ({mode}).")
    except Exception:
        await callback.message.answer(f"Пользователь по тикету #{ticket_id} заблокирован ({mode}).")
    await callback.answer()


@router.callback_query(
    lambda callback: bool(getattr(callback, "data", ""))
    and str(callback.data).startswith(CallbackData.SUPPORT_UNBLOCK_PREFIX)
    and not str(callback.data).startswith(CallbackData.SUPPORT_UNBLOCK_CONFIRM_PREFIX)
)
async def support_unblock_prompt(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id = callback.data.replace(CallbackData.SUPPORT_UNBLOCK_PREFIX, "")
    ticket = await get_ticket(ticket_id)
    if not ticket or ticket.get("topic_code") != "psy":
        await callback.answer("Разблокировка доступна только для психологических тикетов.", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"Подтвердите разблокировку пользователя по тикету #{ticket_id}.",
            reply_markup=ikb.get_support_confirm_kb("unblock", ticket_id),
        )
    except Exception:
        await callback.message.answer(
            f"Подтвердите разблокировку пользователя по тикету #{ticket_id}.",
            reply_markup=ikb.get_support_confirm_kb("unblock", ticket_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_UNBLOCK_CONFIRM_PREFIX))
async def support_unblock_confirm(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_UNBLOCK_CONFIRM_PREFIX, "")
    decision, _, ticket_id = payload.partition("_")
    if decision != "yes":
        await callback.answer("Отменено.")
        return
    ticket = await unblock_actor_by_ticket(ticket_id, callback.from_user.id)
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    try:
        await callback.message.edit_text(f"Пользователь по тикету #{ticket_id} разблокирован.")
    except Exception:
        await callback.message.answer(f"Пользователь по тикету #{ticket_id} разблокирован.")
    await callback.answer()


@router.callback_query(
    lambda callback: bool(getattr(callback, "data", ""))
    and str(callback.data).startswith(CallbackData.SUPPORT_DELETE_PREFIX)
    and not str(callback.data).startswith(CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX)
)
async def support_delete_prompt(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id = callback.data.replace(CallbackData.SUPPORT_DELETE_PREFIX, "")
    ticket = await get_ticket(ticket_id) or await get_ticket(_ticket_id_from_text(str(getattr(callback.message, "text", "") or "")))
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"Подтвердите удаление сообщений тикета #{ticket_id} в рабочих чатах.",
            reply_markup=ikb.get_support_confirm_kb("delete", ticket_id),
        )
    except Exception:
        await callback.message.answer(
            f"Подтвердите удаление сообщений тикета #{ticket_id} в рабочих чатах.",
            reply_markup=ikb.get_support_confirm_kb("delete", ticket_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX))
async def support_delete_confirm(callback: types.CallbackQuery):
    if not await _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX, "")
    decision, _, ticket_id = payload.partition("_")
    if decision != "yes":
        await callback.answer("Отменено.")
        return
    resolved = await get_ticket(ticket_id) or await get_ticket(_ticket_id_from_text(str(getattr(callback.message, "text", "") or "")))
    ticket_id = str(resolved.get("ticket_id")) if resolved else ticket_id
    refs = await ticket_message_refs(ticket_id)
    deleted = 0
    for row in refs:
        try:
            await callback.bot.delete_message(chat_id=int(row["chat_id"]), message_id=int(row["message_id"]))
            deleted += 1
        except Exception:
            continue
    try:
        await callback.message.edit_text(f"Удалено сообщений тикета #{ticket_id}: {deleted}.")
    except Exception:
        await callback.message.answer(f"Удалено сообщений тикета #{ticket_id}: {deleted}.")
    await callback.answer()


@router.message(
    F.reply_to_message,
    lambda message: int(message.chat.id) in _configured_support_chat_ids(),
)
async def psy_staff_reply(message: types.Message):
    reply_to = message.reply_to_message
    if not reply_to:
        return
    ticket = await get_ticket_by_chat_message(message.chat.id, reply_to.message_id)
    if not ticket:
        return
    target_chat_id = _support_target_chat(str(ticket.get("topic_code", "")))
    if target_chat_id is not None and int(message.chat.id) != int(target_chat_id):
        # Защита от случайного reply из нецелевого чата.
        return
    assigned_ids = ticket.get("assigned_staff_ids") or []
    if isinstance(assigned_ids, list):
        allowed = {int(x) for x in assigned_ids if str(x).isdigit() or isinstance(x, int)}
    else:
        allowed = set()
    assigned_staff_id = int(ticket.get("assigned_staff_id") or 0)
    if not allowed and assigned_staff_id:
        allowed = {assigned_staff_id}
    if allowed and int(message.from_user.id) not in allowed:
        await message.answer("Этот тикет назначен другим психологам.")
        return
    if not is_ticket_message_supported(message):
        await message.answer("Этот тип ответа пока не поддерживается.")
        return
    payload = build_message_payload(message)
    updated = await append_staff_payload(
        ticket["ticket_id"],
        message.from_user.id,
        payload,
        staff_username=message.from_user.username,
        staff_full_name=message.from_user.full_name,
    )
    if not updated:
        return
    await register_staff_profile(
        message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    user_id = int(updated["user_id"])
    # Пользователь видит только чистый текст ответа без внутренних технических тегов.
    header = await message.bot.send_message(
        user_id,
        "💬 Вам ответили из службы поддержки.",
    )
    await link_chat_message(updated["ticket_id"], message.message_id, message.chat.id)
    await link_chat_message(updated["ticket_id"], header.message_id, user_id)
    if message.text:
        sent = await message.bot.send_message(user_id, message.text, reply_to_message_id=header.message_id)
        await link_chat_message(updated["ticket_id"], sent.message_id, user_id)
    else:
        copied_id = await copy_with_reply(
            message.bot,
            to_chat_id=int(user_id),
            from_chat_id=int(message.chat.id),
            message_id=int(message.message_id),
            reply_to_message_id=int(header.message_id),
        )
        if copied_id is not None:
            await link_chat_message(updated["ticket_id"], copied_id, user_id)
        else:
            await message.bot.send_message(user_id, "Получен ответ службы поддержки.")
    await message.answer("Ответ доставлен пользователю.")


@router.message(
    lambda message: settings.psycholog_chat_id is not None
    and int(message.chat.id) == int(settings.psycholog_chat_id)
    and not str(message.text or "").startswith("/")
    and not ("Статистика психологов" in str(message.text or "") or "Психолог статистикасы" in str(message.text or ""))
)
async def sync_psycholog_chat_member(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return
    await register_staff_profile(
        message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    # Reply-клавиатуру для статистики не используем — команды надежнее.


@router.message(Command("psy_kb"))
async def psy_kb(message: types.Message):
    if settings.psycholog_chat_id is None or int(message.chat.id) != int(settings.psycholog_chat_id):
        return
    await message.answer(
        "Доступные команды в чате психологов:\n"
        "/psy_stats — статистика психологов\n"
    )


async def _format_psy_stats(period: str) -> str:
    rows = await build_staff_performance(period)
    if not rows:
        return "Статистика не найдена за выбранный период."
    period_label = {
        "all": "за все время",
        "day": "за день",
        "week": "за неделю",
        "month": "за месяц",
        "year": "за год",
    }.get(period, "за все время")
    lines = [f"📊 Статистика психологов {period_label}:"]
    for idx, row in enumerate(rows[:20], start=1):
        profile = row.get("profile", {}) or {}
        username = str(profile.get("username", "")).strip()
        full_name = str(profile.get("full_name", "")).strip()
        label = f"@{username}" if username else (full_name or f"ID {row['staff_id']}")
        lines.append(
            f"{idx}. {label} | ответов: {row['replies']} | тикетов: {row['tickets']} | ср.оценка: {row['avg_rating']} | баллы: {row['quality_points']}"
        )
    return "\n".join(lines)


@router.message(
    lambda message: settings.psycholog_chat_id is not None
    and int(message.chat.id) == int(settings.psycholog_chat_id)
    and bool(message.text)
    and ("Статистика психологов" in str(message.text or "") or "Психолог статистикасы" in str(message.text or ""))
)
@router.message(Command("psy_stats"))
async def psy_stats(message: types.Message):
    if settings.psycholog_chat_id is None or int(message.chat.id) != int(settings.psycholog_chat_id):
        await message.answer("Эта команда доступна только в чате психологов.")
        return
    await message.answer(await _format_psy_stats("all"), reply_markup=ikb.get_psy_stats_period_kb())


@router.message(Command("psy_unblock"))
async def psy_unblock(message: types.Message):
    if settings.psycholog_chat_id is None or int(message.chat.id) != int(settings.psycholog_chat_id):
        return
    if not await _is_psy_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    rows = await list_blocked_actors()
    if not rows:
        await message.answer("Список блокировок пуст.")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for row in rows[:30]:
        key = str(row.get("key") or "")
        until = row.get("until")
        if key.startswith("anon:"):
            actor = f"Аноним #anon_{key.split(':', 1)[1]}"
            payload = f"anon_{key.split(':', 1)[1]}"
        elif key.startswith("user:"):
            actor = f"Пользователь ID {key.split(':', 1)[1]}"
            payload = f"user_{key.split(':', 1)[1]}"
        else:
            actor = key
            payload = key.replace(":", "_")
        duration = "навсегда" if not until else str(until).replace("T", " ")[:16] + " UTC"
        builder.row(
            types.InlineKeyboardButton(
                text=f"✅ Разблокировать: {actor} ({duration})",
                callback_data=f"{CallbackData.PSY_UNBLOCK_PREFIX}{payload}",
            )
        )
    await message.answer("Заблокированные пользователи:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith(CallbackData.PSY_UNBLOCK_PREFIX))
async def psy_unblock_cb(callback: types.CallbackQuery):
    if settings.psycholog_chat_id is None or int(callback.message.chat.id) != int(settings.psycholog_chat_id):
        await callback.answer("Доступно только в чате психологов.", show_alert=True)
        return
    if not await _is_psy_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = str(callback.data).replace(CallbackData.PSY_UNBLOCK_PREFIX, "", 1)
    actor_key = ""
    if payload.startswith("anon_"):
        actor_key = f"anon:{payload.replace('anon_', '', 1)}"
    elif payload.startswith("user_"):
        actor_key = f"user:{payload.replace('user_', '', 1)}"
    else:
        actor_key = payload.replace("_", ":")
    ok = await unblock_actor_by_key(actor_key, callback.from_user.id)
    await callback.answer("Разблокировано." if ok else "Уже разблокирован.", show_alert=True)

@router.callback_query(F.data.startswith(CallbackData.PSY_STATS_PREFIX))
async def psy_stats_period(callback: types.CallbackQuery):
    if settings.psycholog_chat_id is None or int(callback.message.chat.id) != int(settings.psycholog_chat_id):
        await callback.answer("Доступно только в чате психологов.", show_alert=True)
        return
    period = callback.data.replace(CallbackData.PSY_STATS_PREFIX, "")
    await callback.message.edit_text(await _format_psy_stats(period), reply_markup=ikb.get_psy_stats_period_kb())
    await callback.answer()


@router.callback_query(
    lambda callback: bool(getattr(callback, "data", ""))
    and str(callback.data).startswith(CallbackData.SUPPORT_ASSIGN_PREFIX)
    and not str(callback.data).startswith(CallbackData.SUPPORT_ASSIGN_PICK_PREFIX)
    and not str(callback.data).startswith(CallbackData.SUPPORT_ASSIGN_APPLY_PREFIX)
)
async def support_assign_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_psy_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id_raw = callback.data.replace(CallbackData.SUPPORT_ASSIGN_PREFIX, "")
    ticket_id = await _resolve_existing_ticket_id(ticket_id_raw)
    ticket = await get_ticket(ticket_id) or await get_ticket(_ticket_id_from_text(str(getattr(callback.message, "text", "") or "")))
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    staff_rows = await list_staff_registry()
    if settings.psycholog_chat_id is not None:
        try:
            admins = await callback.bot.get_chat_administrators(int(settings.psycholog_chat_id))
            for admin_row in admins:
                user = admin_row.user
                await register_staff_profile(user.id, username=user.username, full_name=user.full_name)
        except Exception:
            pass
        staff_rows = await list_staff_registry()
    if not staff_rows:
        await callback.answer("Нет доступных психологов в реестре.", show_alert=True)
        return
    # Оставляем в списке только тех, кто сейчас состоит в чате психологов.
    active_rows: list[tuple[int, dict[str, str]]] = []
    if settings.psycholog_chat_id is not None:
        for staff_id, profile in staff_rows[:50]:
            try:
                member = await callback.bot.get_chat_member(int(settings.psycholog_chat_id), int(staff_id))
                if str(getattr(member, "status", "")) in {"left", "kicked"}:
                    continue
            except Exception:
                continue
            active_rows.append((staff_id, profile))
    else:
        active_rows = staff_rows[:20]
    if not active_rows:
        await callback.answer("Нет доступных психологов в чате.", show_alert=True)
        return

    # UI назначения отправляем отдельным сообщением, чтобы не затирать карточку тикета.
    initial_selected = set(int(x) for x in (ticket.get("assigned_staff_ids") or []) if isinstance(x, int) or str(x).isdigit())
    ui = await callback.message.answer("Загрузка списка психологов…")
    await state.update_data(assign_ticket_id=str(ticket_id), assign_selected=sorted(initial_selected), assign_ui_message_id=int(ui.message_id))
    await _render_assign_kb(
        callback.bot,
        chat_id=int(ui.chat.id),
        message_id=int(ui.message_id),
        ticket_id=str(ticket_id),
        rows=active_rows,
        selected=set(initial_selected),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_ASSIGN_PICK_PREFIX))
async def support_assign_pick(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_psy_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_ASSIGN_PICK_PREFIX, "")
    ticket_id, sep, staff_id_raw = payload.rpartition("_")
    if not sep:
        await callback.answer("Некорректные данные назначения.", show_alert=True)
        return
    ticket_id = await _resolve_existing_ticket_id(ticket_id)
    if not staff_id_raw.isdigit():
        await callback.answer("Некорректный психолог.", show_alert=True)
        return
    data = await state.get_data()
    current_ticket = str(data.get("assign_ticket_id") or ticket_id)
    ui_message_id = int(data.get("assign_ui_message_id") or 0)
    if not ui_message_id:
        # Если state потерян — создаем новый UI.
        ui = await callback.message.answer("Загрузка списка психологов…")
        ui_message_id = int(ui.message_id)
        await state.update_data(assign_ui_message_id=ui_message_id)
    if str(current_ticket) != str(ticket_id):
        # Если админ параллельно открыл другой тикет — сбрасываем.
        await state.update_data(assign_ticket_id=str(ticket_id), assign_selected=[])
        selected: set[int] = set()
    else:
        raw_sel = data.get("assign_selected") or []
        selected = {int(x) for x in raw_sel if str(x).isdigit() or isinstance(x, int)}
    staff_id = int(staff_id_raw)
    if staff_id in selected:
        selected.remove(staff_id)
    else:
        selected.add(staff_id)
    await state.update_data(assign_ticket_id=str(ticket_id), assign_selected=sorted(selected))

    # Перерисовываем клавиатуру (список актуальных участников чата)
    staff_rows = await list_staff_registry()
    active_rows: list[tuple[int, dict[str, str]]] = []
    if settings.psycholog_chat_id is not None:
        for sid, profile in staff_rows[:50]:
            try:
                member = await callback.bot.get_chat_member(int(settings.psycholog_chat_id), int(sid))
                if str(getattr(member, "status", "")) in {"left", "kicked"}:
                    continue
            except Exception:
                continue
            active_rows.append((sid, profile))
    else:
        active_rows = staff_rows[:20]
    await _render_assign_kb(
        callback.bot,
        chat_id=int(callback.message.chat.id),
        message_id=int(ui_message_id),
        ticket_id=str(ticket_id),
        rows=active_rows,
        selected=selected,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_ASSIGN_APPLY_PREFIX))
async def support_assign_apply(callback: types.CallbackQuery, state: FSMContext):
    if not await _is_psy_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id_raw = callback.data.replace(CallbackData.SUPPORT_ASSIGN_APPLY_PREFIX, "")
    ticket_id = await _resolve_existing_ticket_id(ticket_id_raw)
    data = await state.get_data()
    raw_sel = data.get("assign_selected") or []
    selected = sorted({int(x) for x in raw_sel if str(x).isdigit() or isinstance(x, int)})
    if not selected:
        await callback.answer("Выберите хотя бы одного психолога.", show_alert=True)
        return
    updated = await set_ticket_assignees(ticket_id, selected, callback.from_user.id)
    if not updated:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    # Не сбрасываем галочки: оставляем UI с отмеченными назначенными.
    ui_message_id = int(data.get("assign_ui_message_id") or 0)
    header = f"Назначены психологи (тикет #{ticket_id}): " + ", ".join(str(x) for x in selected)
    if ui_message_id:
        staff_rows = await list_staff_registry()
        active_rows: list[tuple[int, dict[str, str]]] = []
        if settings.psycholog_chat_id is not None:
            for sid, profile in staff_rows[:50]:
                try:
                    member = await callback.bot.get_chat_member(int(settings.psycholog_chat_id), int(sid))
                    if str(getattr(member, "status", "")) in {"left", "kicked"}:
                        continue
                except Exception:
                    continue
                active_rows.append((sid, profile))
        else:
            active_rows = staff_rows[:20]
        try:
            await _render_assign_kb(
                callback.bot,
                chat_id=int(callback.message.chat.id),
                message_id=int(ui_message_id),
                ticket_id=str(ticket_id),
                rows=active_rows,
                selected=set(selected),
                header=header,
            )
        except Exception:
            pass
    await state.update_data(assign_ticket_id=str(ticket_id), assign_selected=selected)
    await callback.answer("Назначено.")

@router.callback_query(F.data == CallbackData.LEVEL_COLL)
async def coll_menu(callback: types.CallbackQuery, state: FSMContext):
    """Главное меню колледжа."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await reset_user_wizard_for_main_menu(state)
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(current_choice="Колледж", admission_track="college")

    from utils.safe_telegram import edit_or_send_text

    text = MESSAGES[lang]["college_menu"]
    await edit_or_send_text(callback.message, text, reply_markup=ikb.get_college_menu(lang))
    approved_profile = await get_approved_user(callback.from_user.id)
    reviewer = await is_responsible_user(callback.from_user.id)
    admin = await is_admin(callback.from_user.id)
    await sync_main_menu_reply_keyboard(
        callback.bot,
        chat_id=callback.message.chat.id,
        lang=lang,
        reply_markup=rkb.get_main_action_kb(
            lang,
            is_registered=approved_profile is not None,
            is_reviewer=reviewer,
            is_admin=admin,
            is_psy_admin=await _is_psy_admin(callback.from_user.id),
        ),
        state=state,
    )
    await callback.answer()


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    await message.answer(await build_applicant_status_text(message.from_user.id))


@router.message(Command("my_data"))
async def cmd_my_data(message: types.Message):
    payload = await build_user_data_export(message.from_user.id)
    pretty = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    buffer = BytesIO(pretty)
    buffer.name = f"user_data_{message.from_user.id}.json"
    await message.answer_document(types.BufferedInputFile(buffer.getvalue(), filename=buffer.name))


@router.message(Command("delete_me"))
async def cmd_delete_me(message: types.Message):
    result = await delete_user_data(message.from_user.id)
    removed_any = any(result.values())
    if not removed_any:
        await message.answer("Данные не найдены.")
        return
    await message.answer("Ваши данные удалены из рабочих хранилищ.")


@router.message(Command("moderation_queue"))
async def cmd_moderation_queue(message: types.Message):
    if not await is_responsible_user(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer(await build_moderation_queue_text())