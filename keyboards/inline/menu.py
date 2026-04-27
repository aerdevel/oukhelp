from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.resources.text_file.catalog import SPECIALTIES_BY_DEPARTMENT
from core.resources.text_file.menus import BUTTONS

def get_back_button(callback_data: str, lang: str) -> InlineKeyboardButton:
    """Создает локализованную кнопку «Назад»."""
    text = "🔙 Назад" if lang == "ru" else "🔙 Артқа"
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def get_back_kb(lang: str, callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(get_back_button(callback_data, lang))
    return builder.as_markup()

def get_lang_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Русский 🇷🇺", callback_data=f"{CallbackData.LANG_PREFIX}ru"))
    builder.row(InlineKeyboardButton(text="Қазақша 🇰🇿", callback_data=f"{CallbackData.LANG_PREFIX}kz"))
    return builder.as_markup()

def get_level_kb(lang: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора уровня обучения."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏛 Университет", callback_data=CallbackData.LEVEL_UNI))
    builder.row(InlineKeyboardButton(text="🏫 Колледж", callback_data=CallbackData.LEVEL_COLL))
    builder.row(get_back_button(CallbackData.START, lang))
    return builder.as_markup()

def get_uni_menu(lang: str, is_registered: bool = False, is_responsible: bool = False) -> InlineKeyboardMarkup:
    """Главное меню университета."""
    btns = BUTTONS[lang]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=btns["about"], callback_data=CallbackData.ABOUT_UNI))
    builder.row(InlineKeyboardButton(text=btns["faculties"], callback_data=CallbackData.FACULTIES))
    builder.row(InlineKeyboardButton(text=btns["price"], callback_data=CallbackData.CALC_START))
    builder.row(InlineKeyboardButton(text=btns["register"], callback_data=CallbackData.FILL_FORM))
    builder.row(InlineKeyboardButton(text=btns["docs"], callback_data=CallbackData.DOCS))
    builder.row(InlineKeyboardButton(text=btns["location"], callback_data=CallbackData.LOCATION))
    builder.row(InlineKeyboardButton(text=btns["socials"], callback_data=CallbackData.SOCIALS))
    # Кнопки кабинета и модерации вынесены в нижнюю reply-клавиатуру.
    builder.row(get_back_button(f"{CallbackData.LANG_PREFIX}{lang}", lang))
    return builder.as_markup()

def get_faculties_kb(lang: str, prefix: str = CallbackData.FAC_PREFIX, back_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    """Клавиатура выбора кафедры."""
    builder = InlineKeyboardBuilder()
    faculties = list(SPECIALTIES_BY_DEPARTMENT[lang].keys())
    for idx, faculty in enumerate(faculties):
        builder.row(InlineKeyboardButton(text=faculty, callback_data=f"{prefix}{idx}"))
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def get_specialties_kb(lang: str, faculty_idx: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора специальности выбранной кафедры."""
    builder = InlineKeyboardBuilder()
    faculties = list(SPECIALTIES_BY_DEPARTMENT[lang].keys())
    selected_faculty = faculties[faculty_idx]
    specialties = SPECIALTIES_BY_DEPARTMENT[lang][selected_faculty]
    for idx, spec in enumerate(specialties):
        builder.row(
            InlineKeyboardButton(
                text=spec,
                callback_data=f"{CallbackData.SPEC_PREFIX}{faculty_idx}_{idx}",
            )
        )
    builder.row(get_back_button(CallbackData.BACK_TO_FACULTY, lang))
    return builder.as_markup()

def get_course_kb(lang: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора курса."""
    builder = InlineKeyboardBuilder()
    courses = ["1", "2", "3", "4", "Graduate"]
    for c in courses:
        label = f"{c} курс" if c != "Graduate" else ("Выпускник" if lang == "ru" else "Түлек")
        builder.button(text=label, callback_data=f"{CallbackData.COURSE_PREFIX}{c}")
    builder.adjust(2)
    builder.row(get_back_button(CallbackData.BACK_TO_SPEC, lang))
    return builder.as_markup()


def get_role_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    roles = (
        [("Студент", "role_student"), ("Выпускник", "role_graduate"), ("Работник", "role_worker"), ("Преподаватель", "role_teacher")]
        if lang == "ru"
        else [("Студент", "role_student"), ("Түлек", "role_graduate"), ("Қызметкер", "role_worker"), ("Оқытушы", "role_teacher")]
    )
    for label, code in roles:
        builder.row(InlineKeyboardButton(text=label, callback_data=code))
    builder.row(get_back_button(CallbackData.FILL_FORM, lang))
    return builder.as_markup()

def get_socials_kb(lang: str) -> InlineKeyboardMarkup:
    """Клавиатура со ссылками на соцсети."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📸 Instagram", url="https://www.instagram.com/ashyk_university/"))
    builder.row(InlineKeyboardButton(text="👤 FaceBook", url="https://www.facebook.com/AshykUniversity/"))
    builder.row(get_back_button(CallbackData.LEVEL_UNI, lang))
    return builder.as_markup()

def get_location_kb(lang: str) -> InlineKeyboardMarkup:
    """Клавиатура с картой и ссылкой на локацию."""
    btns = BUTTONS[lang]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=btns["map"], url="https://go.2gis.com/tYltw"))
    builder.row(get_back_button(CallbackData.LEVEL_UNI, lang))
    return builder.as_markup()


def get_help_menu_kb(lang: str) -> InlineKeyboardMarkup:
    """Раздел помощи в виде компактного меню."""
    builder = InlineKeyboardBuilder()
    if lang == "ru":
        buttons = [
            ("🛠 Техническая поддержка", "tech"),
            ("🧠 Психологическая поддержка", "psy"),
            ("❓ Часто задаваемые вопросы", "faq"),
            ("🎓 Вопрос университету", "uni"),
            ("📘 Жалобы и предложения", "book"),
        ]
    else:
        buttons = [
            ("🛠 Техникалық қолдау", "tech"),
            ("🧠 Психологиялық қолдау", "psy"),
            ("❓ Жиі қойылатын сұрақтар", "faq"),
            ("🎓 Университетке сұрақ", "uni"),
            ("📘 Шағымдар мен ұсыныстар", "book"),
        ]

    for text, code in buttons:
        builder.row(InlineKeyboardButton(text=text, callback_data=f"{CallbackData.HELP_PREFIX}{code}"))
    builder.row(
        InlineKeyboardButton(
            text="🔙 Назад" if lang == "ru" else "🔙 Артқа",
            callback_data=CallbackData.LEVEL_UNI,
        )
    )
    return builder.as_markup()


def get_help_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    """Подтверждение отправки обращения в поддержку."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Отправить" if lang == "ru" else "✅ Жіберу",
            callback_data=CallbackData.HELP_CONFIRM,
        ),
        InlineKeyboardButton(
            text="❌ Сбросить" if lang == "ru" else "❌ Тазарту",
            callback_data=CallbackData.HELP_RESET,
        ),
    )
    return builder.as_markup()


def get_psy_ticket_kb(ticket_id: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🏠 В главное меню" if lang == "ru" else "🏠 Бас мәзірге",
            callback_data=CallbackData.LEVEL_UNI,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Закрыть тикет" if lang == "ru" else "✅ Тикетті жабу",
            callback_data=f"{CallbackData.PSY_CLOSE_PREFIX}{ticket_id}",
        )
    )
    return builder.as_markup()


def get_psy_rating_kb(ticket_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in range(1, 11):
        builder.button(text=str(value), callback_data=f"{CallbackData.PSY_RATE_PREFIX}{ticket_id}_{value}")
    builder.adjust(5)
    return builder.as_markup()


def get_psy_staff_ticket_kb(ticket_id: str, actor_id: str, *, anonymous: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if anonymous:
        builder.row(
            InlineKeyboardButton(text="🚫 Блок 24ч", callback_data=f"{CallbackData.SUPPORT_BLOCK_PREFIX}{ticket_id}_24h"),
            InlineKeyboardButton(text="⛔ Блок навсегда", callback_data=f"{CallbackData.SUPPORT_BLOCK_PREFIX}{ticket_id}_forever"),
        )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить сообщения тикета", callback_data=f"{CallbackData.SUPPORT_DELETE_PREFIX}{ticket_id}")
    )
    return builder.as_markup()


def get_support_confirm_kb(action: str, payload: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    prefix = CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX if action == "block" else CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{prefix}yes_{payload}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"{prefix}no_{payload}"),
    )
    return builder.as_markup()
