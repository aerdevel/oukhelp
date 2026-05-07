from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.callbacks import CallbackData
from core.config import settings
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
    """Финальное подтверждение отправки пакета документов."""
    consent_text = (
        "✅ Согласие на ПД получено"
        if consent_given and lang == "ru"
        else "✅ Дербес дерекке келісім алынды"
        if consent_given
        else "☑️ Дать согласие на обработку ПД"
        if lang == "ru"
        else "☑️ Дербес деректерді өңдеуге келісім беру"
    )
    policy_url = settings.privacy_policy_url.strip()
    policy_button = (
        InlineKeyboardButton(
            text="📄 Политика ПД" if lang == "ru" else "📄 Дерек саясаты",
            url=policy_url,
        )
        if policy_url and "example.com" not in policy_url
        else InlineKeyboardButton(
            text="📄 Политика ПД (не настроена)" if lang == "ru" else "📄 Дерек саясаты (бапталмаған)",
            callback_data=CallbackData.DOC_POLICY_INFO,
        )
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [policy_button],
            [InlineKeyboardButton(text=consent_text, callback_data=CallbackData.DOC_CONSENT)],
            [
                InlineKeyboardButton(
                    text=tr(lang, "✅ Отправить", "✅ Жіберу"),
                    callback_data=CallbackData.CONFIRM_DOCS,
                ),
                InlineKeyboardButton(
                    text=tr(lang, "❌ Сбросить", "❌ Қайта бастау"),
                    callback_data=CallbackData.START_UPLOAD,
                ),
            ]
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

