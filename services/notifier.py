import logging
from aiogram import Bot
from aiogram.types import User
from core.config import settings
from core.curator_const import get_responsible_ids
from keyboards.inline import get_admin_approve_kb, get_documents_review_kb
from utils.privacy import mask_phone, mask_username


async def _resolve_telegram_name(bot: Bot, user_data: dict) -> str:
    """Возвращает отображаемое имя пользователя по Telegram ID."""
    tg_user_id = user_data.get("tg_user_id")
    if tg_user_id is None:
        return user_data.get("tg_full_name") or user_data.get("fio") or "Неизвестно"

    try:
        chat = await bot.get_chat(int(tg_user_id))
        return chat.full_name or user_data.get("tg_full_name") or user_data.get("fio") or "Неизвестно"
    except Exception:
        return user_data.get("tg_full_name") or user_data.get("fio") or "Неизвестно"


async def notify_responsible_new_registration(bot: Bot, user_data: dict):
    """Отправляет уведомление о новой регистрации ответственному сотруднику."""
    role = user_data.get("role")
    group = user_data.get("group")
    specialty = user_data.get("specialty")
    user_phone = user_data.get("phone")
    tg_user_id = user_data.get("tg_user_id")
    tg_username = user_data.get("tg_username")
    telegram_name = await _resolve_telegram_name(bot, user_data)
    
    # Определение всех получателей уведомления по группе.
    target_chat_ids = get_responsible_ids(group or "-", specialty)
    
    # Формирование текста уведомления.
    username_text = f"@{tg_username}" if tg_username else "-"
    user_data["responsible_ids"] = target_chat_ids
    text = (
        f"👤 Telegram: {telegram_name}\n"
        f"🆔 Telegram ID: {tg_user_id or '-'}\n"
        f"🔗 Username: {username_text}\n"
        f"📋 ФИО: {user_data.get('fio')}\n"
        f"📞 Тел: {user_phone}\n"
        f"🎭 Статус: {role}\n"
        f"🏛 Кафедра: {user_data.get('faculty', '-')}\n"
        f"📖 Спец: {user_data.get('specialty', '-')}\n"
    )
    if role in {"Студент", "Выпускник", "Преподаватель"}:
        text += f"📚 Группа: {group}\n"
    if role == "Студент":
        text += f"🎓 Курс: {user_data.get('course')}\n"

    # Кнопки модерации заявки.
    kb = get_admin_approve_kb(user_phone)

    for target_chat_id in target_chat_ids:
        try:
            await bot.send_message(chat_id=target_chat_id, text=text, reply_markup=kb)
        except Exception as err:
            logging.exception("Ошибка при отправке уведомления куратору %s: %s", target_chat_id, err)
            try:
                safe_text = (
                    "⚠️ Ошибка уведомления куратора\n\n"
                    f"🆔 Пользователь: {tg_user_id or '-'}\n"
                    f"📞 Телефон: {mask_phone(str(user_phone or ''))}\n"
                    f"🔗 Username: {mask_username(str(tg_username or ''))}\n"
                    f"📨 Не доставлено в чат: {target_chat_id}"
                )
                await bot.send_message(chat_id=settings.admin_id, text=safe_text)
            except Exception as fallback_err:
                logging.exception("Ошибка резервного уведомления админу: %s", fallback_err)

async def notify_admin_document(
    bot: Bot,
    user_full_name: str,
    doc_type: str,
    message_with_file,
    sender_user: User | None = None,
):
    """Пересылает файл документа в чат приемной комиссии."""
    if sender_user:
        mention = f"{sender_user.full_name}"
        username_text = f"@{sender_user.username}" if sender_user.username else "-"
        telegram_info = (
            f"👤 От: {mention}\n"
            f"🆔 Telegram ID: {sender_user.id}\n"
            f"🔗 Username: {username_text}\n"
        )
    else:
        telegram_info = f"👤 От: {user_full_name}\n"

    caption = (
        f"📄 Новый документ\n\n"
        f"{telegram_info}"
        f"📌 Тип: {doc_type}"
    )
    
    try:
        # Отправка файла в чат приемной комиссии.
        if getattr(message_with_file, "photo", None):
            await bot.send_photo(
                chat_id=settings.priemka_id,
                photo=message_with_file.photo[-1].file_id, 
                caption=caption
            )
        elif getattr(message_with_file, "document", None):
            await bot.send_document(
                chat_id=settings.priemka_id,
                document=message_with_file.document.file_id, 
                caption=caption
            )
        else:
            await bot.send_message(chat_id=settings.priemka_id, text=caption)
    except Exception as err:
        logging.error("Ошибка при пересылке документа: %s", err)


async def send_documents_package_for_review(bot: Bot, package: dict):
    """Отправляет цельный пакет документов в чат приемной комиссии."""
    review_chat_id = settings.moderation_chat_id
    username_text = f"@{package.get('tg_username')}" if package.get("tg_username") else "-"
    tg_user_id = package["tg_user_id"]
    summary = (
        "📦 Новый пакет документов\n\n"
        f"👤 ФИО: {package.get('fio', '-')}\n"
        f"📞 Телефон: {package.get('phone', '-')}\n"
        f"🆔 Telegram ID: {tg_user_id}\n"
        f"🔗 Username: {username_text}\n"
        f"🎭 Статус: {package.get('role', '-')}\n"
        f"📚 Группа: {package.get('group', '-')}\n"
        "Нажмите на нужный документ в кнопках ниже, чтобы открыть его прямо в чате."
    )
    kb = get_documents_review_kb(tg_user_id)
    await bot.send_message(review_chat_id, summary, reply_markup=kb)