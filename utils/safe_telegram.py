"""Безопасные обёртки над Telegram Bot API для aiogram.

Telegram возвращает 400 «message is not modified», если текст и разметка
совпадают с уже отображёнными. Такие запросы не являются ошибкой домена:
их глушим, чтобы не засорять логи и не ронять пайплайн обработки update.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest


def _is_message_not_modified(exc: TelegramBadRequest) -> bool:
    msg = (getattr(exc, "message", None) or str(exc) or "").lower()
    return "message is not modified" in msg


def _is_not_editable(exc: TelegramBadRequest) -> bool:
    msg = (getattr(exc, "message", None) or str(exc) or "").lower()
    return "there is no text in the message to edit" in msg or "message can't be edited" in msg


async def edit_or_send_text(
    message: types.Message,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | types.ReplyKeyboardMarkup | None = None,
    **kwargs: Any,
) -> types.Message:
    """Редактирует текст/caption или отправляет новое сообщение (после фото/медиа)."""
    if message.text is not None:
        try:
            await message.edit_text(text, reply_markup=reply_markup, **kwargs)
            return message
        except TelegramBadRequest as exc:
            if _is_message_not_modified(exc) or _is_not_editable(exc):
                pass
            else:
                raise
    elif message.caption is not None:
        try:
            await message.edit_caption(caption=text, reply_markup=reply_markup, **kwargs)
            return message
        except TelegramBadRequest as exc:
            if _is_message_not_modified(exc) or _is_not_editable(exc):
                pass
            else:
                raise
    return await message.answer(text, reply_markup=reply_markup, **kwargs)


async def safe_edit_message_text(
    message: types.Message,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    **kwargs: Any,
) -> bool:
    """edit_text; False если контент не изменился (идемпотентный no-op)."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, **kwargs)
        return True
    except TelegramBadRequest as exc:
        if _is_message_not_modified(exc) or _is_not_editable(exc):
            await message.answer(text, reply_markup=reply_markup, **kwargs)
            return True
        raise


async def safe_edit_reply_markup(
    message: types.Message,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    **kwargs: Any,
) -> bool:
    """edit_reply_markup; False если разметка не изменилась."""
    try:
        await message.edit_reply_markup(reply_markup=reply_markup, **kwargs)
        return True
    except TelegramBadRequest as exc:
        if _is_message_not_modified(exc):
            return False
        raise


async def safe_edit_message_text_by_id(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | types.ReplyKeyboardMarkup | None = None,
    **kwargs: Any,
) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=reply_markup,
            **kwargs,
        )
        return True
    except TelegramBadRequest as exc:
        if _is_message_not_modified(exc):
            return False
        raise
