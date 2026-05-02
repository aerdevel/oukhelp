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
from services.status import build_applicant_status_text, build_moderation_queue_text
from services.support_tickets import (
    append_staff_payload,
    append_user_payload,
    block_actor_by_ticket,
    close_ticket,
    get_ticket,
    get_ticket_by_chat_message,
    is_actor_blocked,
    link_chat_message,
    open_or_get_ticket,
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

router = Router()
def _can_manage_support(from_user_id: int) -> bool:
    return bool(is_admin(from_user_id) or is_responsible_user(from_user_id))



def _keyboard_anchor_text(lang: str) -> str:
    """Техническое сообщение для гарантированного показа reply-клавиатуры.

    Telegram не отправляет сообщение с пустым текстом, поэтому
    используем короткий нейтральный якорь.
    """
    return tr(lang, "⬇️ Меню", "⬇️ Мәзір")


def _support_target_chat(topic_code: str) -> int | None:
    if topic_code == "psy":
        return settings.psycholog_chat_id
    if topic_code == "uni":
        return settings.moderation_chat_id
    return None


def _ticket_search_tags(ticket: dict) -> tuple[str, str]:
    ticket_tag = f"#ticket_{ticket['ticket_id']}"
    if ticket.get("anonymous"):
        actor_tag = f"#anon_{ticket['anonymous_id']}"
    else:
        actor_tag = f"#user_{ticket['user_id']}"
    return ticket_tag, actor_tag


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
    if data.get("psy_ticket_id"):
        # Выход из режима ввода сообщений психологу без закрытия тикета.
        await state.set_state(None)
    
    await state.update_data(current_choice="Университет")
    
    text = MESSAGES[lang]["main_menu"]
    approved_profile = get_approved_user(callback.from_user.id)
    reviewer = is_responsible_user(callback.from_user.id)
    admin = is_admin(callback.from_user.id)
    await callback.message.edit_text(
        text,
        reply_markup=ikb.get_uni_menu(
            lang,
            is_registered=approved_profile is not None,
            is_responsible=reviewer,
        ),
    )
    if not data.get("action_kb_initialized", False):
        await callback.message.answer(
            _keyboard_anchor_text(lang),
            reply_markup=rkb.get_main_action_kb(
                lang,
                is_registered=approved_profile is not None,
                is_reviewer=reviewer,
                is_admin=admin,
            ),
        )
        await state.update_data(action_kb_initialized=True)
    await callback.answer()


@router.message(F.text.in_(["🏠 Главное меню", "🏠 Басты мәзір"]))
async def main_menu_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if data.get("psy_ticket_id"):
        await state.set_state(None)
    approved_profile = get_approved_user(message.from_user.id)
    reviewer = is_responsible_user(message.from_user.id)
    admin = is_admin(message.from_user.id)
    await message.answer(MESSAGES[lang]["main_menu"], reply_markup=ikb.get_uni_menu(lang))
    if not data.get("action_kb_initialized", False):
        await message.answer(
            _keyboard_anchor_text(lang),
            reply_markup=rkb.get_main_action_kb(
                lang,
                is_registered=approved_profile is not None,
                is_reviewer=reviewer,
                is_admin=admin,
            ),
        )
        await state.update_data(action_kb_initialized=True)


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
    await message.answer(title, reply_markup=ikb.get_help_menu_kb(lang))


@router.callback_query(F.data.startswith(CallbackData.HELP_PREFIX))
async def help_option(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    code = callback.data.replace(CallbackData.HELP_PREFIX, "")
    labels = {
        "ru": {
            "tech": "Техническая поддержка",
            "psy": "Психологическая поддержка",
            "faq": "Часто задаваемые вопросы",
            "uni": "Вопрос университету",
            "book": "Книга жалоб и предложений",
        },
        "kz": {
            "tech": "Техникалық қолдау",
            "psy": "Психологиялық қолдау",
            "faq": "Жиі қойылатын сұрақтар",
            "uni": "Университетке сұрақ",
            "book": "Шағымдар мен ұсыныстар кітабы",
        },
    }
    selected = labels.get(lang, labels["ru"]).get(code)
    if not selected:
        await callback.answer("Неизвестный раздел.", show_alert=True)
        return
    if code == "psy":
        ticket = open_or_get_ticket(callback.from_user.id, "psy", anonymous=True)
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
            reply_markup=ikb.get_psy_ticket_kb(ticket["ticket_id"], lang),
        )
        await callback.answer(tr(lang, "Психологический тикет открыт.", "Психологиялық тикет ашылды."))
        return
    if code == "uni":
        ticket = open_or_get_ticket(callback.from_user.id, "uni", anonymous=False)
        await state.update_data(support_ticket_id=ticket["ticket_id"], help_topic_code="uni")
        await state.set_state(HelpRequest.waiting_for_text)
        await callback.message.answer(
            tr(
                lang,
                f"🎓 Чат с приемной комиссией открыт.\nТикет #{ticket['ticket_id']}.\n"
                "Напишите сообщение. Можно выйти в меню, тикет останется активным.",
                f"🎓 Қабылдау комиссиясымен чат ашылды.\nТикет #{ticket['ticket_id']}.\n"
                "Хабарлама жазыңыз. Мәзірге шықсаңыз да, тикет ашық қалады.",
            ),
            reply_markup=ikb.get_psy_ticket_kb(ticket["ticket_id"], lang),
        )
        await callback.answer(tr(lang, "Тикет в приемную открыт.", "Қабылдау комиссиясына тикет ашылды."))
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
            ticket = open_or_get_ticket(message.from_user.id, support_topic or "psy", anonymous=(support_topic != "uni"))
            support_ticket_id = str(ticket["ticket_id"])
        existing_ticket = get_ticket(support_ticket_id)
        effective_topic = str(existing_ticket.get("topic_code")) if existing_ticket else (support_topic or "psy")
        is_anon = bool(existing_ticket.get("anonymous")) if existing_ticket else (effective_topic != "uni")
        blocked, blocked_until = is_actor_blocked(
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
        ticket = append_user_payload(ticket_id, payload)
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
        link_chat_message(ticket["ticket_id"], sent.message_id, actual_chat_id)
        copied_id = await copy_with_reply(
            message.bot,
            to_chat_id=int(actual_chat_id),
            from_chat_id=int(message.chat.id),
            message_id=int(message.message_id),
            reply_to_message_id=int(sent.message_id),
        )
        if copied_id is not None:
            link_chat_message(ticket["ticket_id"], copied_id, actual_chat_id)
        await message.answer(
            tr(
                lang,
                "✨ Сообщение отправлено психологам.\nОжидайте ответ.",
                "✨ Хабарлама психологтарға жіберілді.\nЖауап күтіңіз.",
            ),
            reply_markup=ikb.get_psy_ticket_kb(ticket["ticket_id"], lang),
        )
        return

    if len(text) < 5:
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
    ticket = get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(callback.from_user.id):
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    closed = close_ticket(ticket_id, closed_by_user=True)
    await state.update_data(psy_ticket_id=None)
    await state.update_data(support_ticket_id=None)
    if closed:
        target_chat_id = _support_target_chat(str(closed.get("topic_code", "")))
        if target_chat_id:
            await callback.bot.send_message(
                int(target_chat_id),
                "✅ Тикет закрыт пользователем\n"
                f"Тикет: #ticket_{ticket_id}\n"
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
    ticket = get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(callback.from_user.id):
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    set_ticket_rating(ticket_id, rating)
    await state.update_data(rating_ticket_id=ticket_id, rating_value=rating)
    await state.set_state(HelpRequest.waiting_for_rating_comment)
    await callback.message.edit_text("Спасибо! Теперь напишите комментарий к оценке ")
    await callback.answer()


@router.message(HelpRequest.waiting_for_rating_comment)
async def psy_rating_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = str(data.get("rating_ticket_id", ""))
    rating_value = int(data.get("rating_value", 0))
    ticket = get_ticket(ticket_id)
    if not ticket or int(ticket.get("user_id", 0)) != int(message.from_user.id):
        await message.answer("Тикет не найден.")
        await state.clear()
        return
    comment = (message.text or "").strip()
    if len(comment) < 3:
        await message.answer("Напишите комментарий чуть подробнее (минимум 3 символа).")
        return
    set_ticket_rating_comment(ticket_id, comment)
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
    ticket = get_ticket(ticket_id)
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
    rows = tickets_by_alias(alias)
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


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_BLOCK_PREFIX))
async def support_block_prompt(callback: types.CallbackQuery):
    if not _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_BLOCK_PREFIX, "")
    ticket_id, _, mode = payload.partition("_")
    ticket = get_ticket(ticket_id)
    if not ticket or ticket.get("topic_code") != "psy":
        await callback.answer("Блокировка доступна только для анонимных психологических тикетов.", show_alert=True)
        return
    mode_label = "24 часа" if mode == "24h" else "навсегда"
    await callback.message.answer(
        f"Подтвердите блокировку анонима по тикету #{ticket_id} ({mode_label}).",
        reply_markup=ikb.get_support_confirm_kb("block", payload),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX))
async def support_block_confirm(callback: types.CallbackQuery):
    if not _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX, "")
    decision, _, rest = payload.partition("_")
    if decision != "yes":
        await callback.answer("Отменено.")
        return
    ticket_id, _, mode = rest.partition("_")
    ticket = block_actor_by_ticket(ticket_id, mode, callback.from_user.id)
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    await callback.message.answer(f"Аноним по тикету #{ticket_id} заблокирован ({mode}).")
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_DELETE_PREFIX))
async def support_delete_prompt(callback: types.CallbackQuery):
    if not _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id = callback.data.replace(CallbackData.SUPPORT_DELETE_PREFIX, "")
    ticket = get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден.", show_alert=True)
        return
    await callback.message.answer(
        f"Подтвердите удаление сообщений тикета #{ticket_id} в рабочих чатах.",
        reply_markup=ikb.get_support_confirm_kb("delete", ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX))
async def support_delete_confirm(callback: types.CallbackQuery):
    if not _can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX, "")
    decision, _, ticket_id = payload.partition("_")
    if decision != "yes":
        await callback.answer("Отменено.")
        return
    refs = ticket_message_refs(ticket_id)
    deleted = 0
    for row in refs:
        try:
            await callback.bot.delete_message(chat_id=int(row["chat_id"]), message_id=int(row["message_id"]))
            deleted += 1
        except Exception:
            continue
    await callback.message.answer(f"Удалено сообщений тикета #{ticket_id}: {deleted}.")
    await callback.answer()


@router.message(
    F.reply_to_message,
    lambda message: int(message.chat.id) in {
        int(settings.psycholog_chat_id),
        int(settings.moderation_chat_id),
    },
)
async def psy_staff_reply(message: types.Message):
    reply_to = message.reply_to_message
    if not reply_to:
        return
    ticket = get_ticket_by_chat_message(message.chat.id, reply_to.message_id)
    if not ticket:
        return
    target_chat_id = _support_target_chat(str(ticket.get("topic_code", "")))
    if target_chat_id is not None and int(message.chat.id) != int(target_chat_id):
        # Защита от случайного reply из нецелевого чата.
        return
    if not is_ticket_message_supported(message):
        await message.answer("Этот тип ответа пока не поддерживается.")
        return
    payload = build_message_payload(message)
    updated = append_staff_payload(
        ticket["ticket_id"],
        message.from_user.id,
        payload,
        staff_username=message.from_user.username,
        staff_full_name=message.from_user.full_name,
    )
    if not updated:
        return
    user_id = int(updated["user_id"])
    # Пользователь видит только чистый текст ответа без внутренних технических тегов.
    header = await message.bot.send_message(
        user_id,
        "💬 Вам ответили из службы поддержки.",
    )
    link_chat_message(updated["ticket_id"], message.message_id, message.chat.id)
    link_chat_message(updated["ticket_id"], header.message_id, user_id)
    if message.text:
        sent = await message.bot.send_message(user_id, message.text, reply_to_message_id=header.message_id)
        link_chat_message(updated["ticket_id"], sent.message_id, user_id)
    else:
        copied_id = await copy_with_reply(
            message.bot,
            to_chat_id=int(user_id),
            from_chat_id=int(message.chat.id),
            message_id=int(message.message_id),
            reply_to_message_id=int(header.message_id),
        )
        if copied_id is not None:
            link_chat_message(updated["ticket_id"], copied_id, user_id)
        else:
            await message.bot.send_message(user_id, "Получен ответ службы поддержки.")
    await message.answer("Ответ доставлен пользователю.")

@router.callback_query(F.data == CallbackData.LEVEL_COLL)
async def coll_menu(callback: types.CallbackQuery, state: FSMContext):
    """Отображает меню колледжа."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    await state.update_data(current_choice="Колледж")
    
    text = MESSAGES[lang]["under_dev"]
    await callback.message.edit_text(
        text, 
        reply_markup=ikb.get_back_kb(lang, f"{CallbackData.LANG_PREFIX}{lang}")
    )
    await callback.answer()


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    await message.answer(build_applicant_status_text(message.from_user.id))


@router.message(Command("my_data"))
async def cmd_my_data(message: types.Message):
    payload = build_user_data_export(message.from_user.id)
    pretty = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    buffer = BytesIO(pretty)
    buffer.name = f"user_data_{message.from_user.id}.json"
    await message.answer_document(types.BufferedInputFile(buffer.getvalue(), filename=buffer.name))


@router.message(Command("delete_me"))
async def cmd_delete_me(message: types.Message):
    result = delete_user_data(message.from_user.id)
    removed_any = any(result.values())
    if not removed_any:
        await message.answer("Данные не найдены.")
        return
    await message.answer("Ваши данные удалены из рабочих хранилищ.")


@router.message(Command("moderation_queue"))
async def cmd_moderation_queue(message: types.Message):
    if not is_responsible_user(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer(build_moderation_queue_text())