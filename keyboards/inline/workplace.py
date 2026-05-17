from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from utils.i18n import tr


def get_workplace_hub_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🛂 Заявки на регистрацию", "🛂 Тіркеу өтінімдері"),
            callback_data=CallbackData.STAFF_WP_REVIEW,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "✉️ Уведомление студентам", "✉️ Студенттерге хабарлама"),
            callback_data=CallbackData.STAFF_WP_NOTIFY,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "📅 Расписание", "📅 Кесте"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🎉 Мероприятие", "🎉 Іс-шара"),
            callback_data=CallbackData.STAFF_WP_EVENT,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔄 Сменить группу", "🔄 Топты өзгерту"),
            callback_data=CallbackData.STAFF_REASSIGN_START,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔙 В личный кабинет", "🔙 Жеке кабинетке"),
            callback_data=CallbackData.MY_CABINET,
        )
    )
    return b.as_markup()


def get_workplace_schedule_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "👀 Просмотр расписания", "👀 Кестені қарау"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE_VIEW,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "📷 Загрузить фото расписания", "📷 Кесте фотосын жүктеу"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE_UPLOAD,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "📣 Отправить расписание группам", "📣 Топтарға кесте жіберу"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE_SEND,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔙 Рабочее место", "🔙 Жұмыс орны"),
            callback_data=CallbackData.CABINET_WORKPLACE,
        )
    )
    return b.as_markup()


def get_workplace_notify_filters_kb(lang: str, nf: dict) -> InlineKeyboardMarkup:
    p = "wpfil_"
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text=tr(lang, "Трек: универ", "Трек: универ"), callback_data=f"{p}track_uni"),
        InlineKeyboardButton(text=tr(lang, "Трек: колледж", "Трек: колледж"), callback_data=f"{p}track_college"),
    )
    b.row(
        InlineKeyboardButton(text=tr(lang, "Роль: студент", "Рөл: студент"), callback_data=f"{p}role_stud"),
        InlineKeyboardButton(text=tr(lang, "Роль: выпускник", "Рөл: түлек"), callback_data=f"{p}role_grad"),
    )
    b.row(
        InlineKeyboardButton(text=tr(lang, "Без фильтра спец.", "Мамандықсыз"), callback_data=f"{p}skip_spec"),
        InlineKeyboardButton(text=tr(lang, "Готово", "Дайын"), callback_data=f"{p}done"),
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔙 Рабочее место", "🔙 Жұмыс орны"),
            callback_data=CallbackData.CABINET_WORKPLACE,
        )
    )
    b.row(InlineKeyboardButton(text=tr(lang, "Отмена", "Болдырмау"), callback_data=CallbackData.STAFF_WP_ABORT))
    return b.as_markup()


def get_student_schedule_back_kb(lang: str, menu_callback: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔙 В личный кабинет", "🔙 Жеке кабинетке"),
            callback_data=CallbackData.MY_CABINET,
        )
    )
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🏠 Главное меню", "🏠 Бас мәзір"),
            callback_data=menu_callback,
        )
    )
    return b.as_markup()


def get_workplace_group_pick_kb(lang: str, groups: list[str], *, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for name in groups[:25]:
        safe = name.replace(" ", "_")[:40]
        b.row(InlineKeyboardButton(text=name, callback_data=f"{prefix}{safe}"))
    b.row(
        InlineKeyboardButton(
            text=tr(lang, "🔙 Назад", "🔙 Артқа"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE,
        )
    )
    return b.as_markup()
