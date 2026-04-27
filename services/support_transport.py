from __future__ import annotations

from aiogram import Bot, types


def is_ticket_message_supported(message: types.Message) -> bool:
    """Разрешенные типы контента в тикетах поддержки."""
    return bool(
        message.text
        or message.caption
        or message.photo
        or message.document
        or message.sticker
        or message.animation
        or message.video
        or message.voice
    )


def build_message_payload(message: types.Message) -> dict[str, str]:
    """Строит компактный payload для журнала тикета."""
    if message.text:
        return {"kind": "text", "preview": message.text[:500]}
    if message.caption:
        return {"kind": "caption", "preview": message.caption[:500]}
    if message.sticker:
        return {"kind": "sticker", "preview": f"sticker:{message.sticker.emoji or '-'}"}
    if message.animation:
        return {"kind": "gif", "preview": "animation"}
    if message.photo:
        return {"kind": "photo", "preview": "photo"}
    if message.document:
        return {"kind": "document", "preview": message.document.file_name or "document"}
    if message.video:
        return {"kind": "video", "preview": "video"}
    if message.voice:
        return {"kind": "voice", "preview": "voice"}
    return {"kind": "other", "preview": "unsupported"}


async def copy_with_reply(
    bot: Bot,
    *,
    to_chat_id: int,
    from_chat_id: int,
    message_id: int,
    reply_to_message_id: int,
) -> int | None:
    """Копирует сообщение в другой чат и возвращает новый message_id."""
    try:
        copied = await bot.copy_message(
            chat_id=to_chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
        )
        return int(copied.message_id)
    except Exception:
        return None
