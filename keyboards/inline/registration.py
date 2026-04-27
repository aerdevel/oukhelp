from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.callbacks import CallbackData
from utils.i18n import tr


def get_registration_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    """Подтверждение или сброс анкеты перед отправкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(lang, "✅ Подтвердить", "✅ Растау"),
                    callback_data=CallbackData.CONFIRM_FINAL,
                ),
                InlineKeyboardButton(
                    text=tr(lang, "❌ Сбросить", "❌ Жою"),
                    callback_data=CallbackData.FILL_FORM,
                ),
            ]
        ]
    )

