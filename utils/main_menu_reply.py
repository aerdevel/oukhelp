"""Reply-клавиатура главного меню: одно закреплённое служебное сообщение на чат.

Инвариант: не плодим цепочку служебных сообщений при каждом заходе в главное меню.
Если message_id уже сохранён в FSM — обновляем его; иначе создаём один якорь.
"""

from __future__ import annotations

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from utils.i18n import tr
from utils.safe_telegram import safe_edit_message_text_by_id


def main_menu_reply_hint(lang: str) -> str:
    """Короткий видимый текст: Telegram не принимает полностью пустое тело сообщения."""
    return tr(
        lang,
        "Нижняя панель: быстрые действия и сервисные кнопки.",
        "Төменгі панель: жылдам әрекеттер мен қызметтік батырмалар.",
    )


async def sync_main_menu_reply_keyboard(
    bot: Bot,
    *,
    chat_id: int,
    lang: str,
    reply_markup: types.ReplyKeyboardMarkup,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    mid = data.get("action_kb_message_id")
    cid = data.get("action_kb_chat_id")
    text = main_menu_reply_hint(lang)
    if mid and cid and int(cid) == int(chat_id):
        try:
            await safe_edit_message_text_by_id(
                bot,
                chat_id=int(chat_id),
                message_id=int(mid),
                text=text,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            err = str(exc).lower()
            if "message to edit not found" in err or "message can't be edited" in err:
                sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
                await state.update_data(
                    action_kb_message_id=sent.message_id,
                    action_kb_chat_id=sent.chat.id,
                    action_kb_initialized=True,
                )
                return
            raise
        await state.update_data(action_kb_initialized=True)
        return
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await state.update_data(
        action_kb_message_id=sent.message_id,
        action_kb_chat_id=sent.chat.id,
        action_kb_initialized=True,
    )
