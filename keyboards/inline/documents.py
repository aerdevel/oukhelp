from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.callbacks import CallbackData
from core.resources.text_file.menus import BUTTONS
from utils.i18n import tr


def get_docs_list_kb(lang: str, back_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    """Кнопки входа в загрузку документов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTONS[lang]["send_docs"], callback_data=CallbackData.START_UPLOAD)],
            [InlineKeyboardButton(text=BUTTONS[lang]["back"], callback_data=back_callback)],
        ]
    )


def get_docs_confirm_kb(lang: str, *, consent_given: bool = False) -> InlineKeyboardMarkup:
    """Финальное подтверждение: только согласие на обработку ПД (без внешней ссылки на политику)."""
    if consent_given:
        consent_text = (
            "✅ Согласие на обработку ПД получено"
            if lang == "ru"
            else "✅ Дербес деректерді өңдеуге келісім алынды"
        )
    else:
        consent_text = (
            "☑️ Даю согласие на обработку персональных данных"
            if lang == "ru"
            else "☑️ Дербес деректерді өңдеуге келісім беремін"
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=consent_text, callback_data=CallbackData.DOC_CONSENT)],
            [
                InlineKeyboardButton(
                    text=tr(lang, "✅ Отправить", "✅ Жіберу"),
                    callback_data=CallbackData.CONFIRM_DOCS,
                ),
                InlineKeyboardButton(
                    text=tr(lang, "🔙 Назад", "🔙 Артқа"),
                    callback_data=CallbackData.DOC_BACK_FROM_CONFIRM,
                ),
            ],
        ]
    )


def get_docs_done_kb(lang: str, menu_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    """Возврат в главное меню после отправки пакета."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(lang, "🏠 В главное меню", "🏠 Бас мәзірге"),
                    callback_data=menu_callback,
                )
            ]
        ]
    )
