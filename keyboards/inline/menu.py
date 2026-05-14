import re

from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.resources.text_file.catalog import get_specialties_by_department
from core.resources.text_file.menus import BUTTONS
from utils.i18n import tr

# Сколько специальностей на одной странице инлайн-клавиатуры (Telegram ограничивает размер текста кнопки).
SPECIALTY_PAGE_SIZE = 6


def _shorten_button_text(text: str, max_len: int = 54) -> str:
    """Укорачивает подпись на кнопке, чтобы не упираться в лимиты Telegram."""
    cleaned = (text or "").strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def specialty_pick_header(lang: str, track: str, department_title: str, page: int, total_pages: int) -> str:
    """Заголовок экрана выбора специальности (с пагинацией)."""
    safe_page = page + 1
    if track == "college":
        if lang == "ru":
            head = f"Бірлестік / объединение:\n{department_title}\nСтраница {safe_page}/{total_pages}\n\nВыберите специальность:"
        else:
            head = f"Бірлестік:\n{department_title}\nБет {safe_page}/{total_pages}\n\nМамандықты таңдаңыз:"
        return head
    if lang == "ru":
        return f"Кафедра:\n{department_title}\nСтраница {safe_page}/{total_pages}\n\nВыберите специальность:"
    return f"Кафедра:\n{department_title}\nБет {safe_page}/{total_pages}\n\nМамандықты таңдаңыз:"


def get_specialties_paged_kb(
    lang: str,
    faculty_idx: int,
    track: str,
    page: int,
    *,
    spec_prefix: str,
    page_prefix: str,
    back_callback: str,
) -> InlineKeyboardMarkup:
    """Специальности выбранного подразделения с постраничной навигацией."""
    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    if faculty_idx < 0 or faculty_idx >= len(faculties):
        builder = InlineKeyboardBuilder()
        builder.row(get_back_button(back_callback, lang))
        return builder.as_markup()
    specs = specialties_by_department[faculties[faculty_idx]]
    total = len(specs)
    total_pages = max(1, ceil(total / SPECIALTY_PAGE_SIZE))
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * SPECIALTY_PAGE_SIZE
    chunk = specs[start : start + SPECIALTY_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for offset, spec in enumerate(chunk):
        abs_idx = start + offset
        builder.row(
            InlineKeyboardButton(
                text=_shorten_button_text(spec),
                callback_data=f"{spec_prefix}{faculty_idx}_{abs_idx}",
            )
        )
    nav: list[InlineKeyboardButton] = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{page_prefix}{faculty_idx}_{safe_page - 1}"))
    if safe_page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{page_prefix}{faculty_idx}_{safe_page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def _digits(value: object) -> str:
    """Извлекает цифры, чтобы callback_data был коротким и валидным.

    В Telegram `callback_data` должно быть <= 64 байт. `ticket_id` иногда приходит
    в разных формах (например, "#ticket_10014"), поэтому нормализуем до "10014".
    """
    raw = str(value or "")
    found = re.findall(r"\d+", raw)
    return found[0] if found else raw

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
    builder.row(InlineKeyboardButton(text=btns["register"], callback_data=CallbackData.FILL_FORM))
    builder.row(InlineKeyboardButton(text=btns["docs"], callback_data=CallbackData.DOCS))
    builder.row(InlineKeyboardButton(text=btns["location"], callback_data=CallbackData.LOCATION))
    builder.row(InlineKeyboardButton(text=btns["socials"], callback_data=CallbackData.SOCIALS))
    # Кнопки кабинета и модерации вынесены в нижнюю reply-клавиатуру.
    builder.row(get_back_button(f"{CallbackData.LANG_PREFIX}{lang}", lang))
    return builder.as_markup()


def get_college_menu(lang: str) -> InlineKeyboardMarkup:
    """Главное меню колледжа без дублирования университетских сценариев."""
    btns = BUTTONS[lang]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=btns["about_college"], callback_data=CallbackData.ABOUT_COLL))
    builder.row(InlineKeyboardButton(text=btns["faculties"], callback_data=CallbackData.FACULTIES))
    builder.row(InlineKeyboardButton(text=btns["register"], callback_data=CallbackData.FILL_FORM))
    builder.row(InlineKeyboardButton(text=btns["docs"], callback_data=CallbackData.DOCS))
    builder.row(InlineKeyboardButton(text=btns["location"], callback_data=CallbackData.LOCATION))
    builder.row(InlineKeyboardButton(text=btns["socials"], callback_data=CallbackData.SOCIALS))
    builder.row(get_back_button(f"{CallbackData.LANG_PREFIX}{lang}", lang))
    return builder.as_markup()


def get_about_college_kb(lang: str, back_callback: str = CallbackData.LEVEL_COLL) -> InlineKeyboardMarkup:
    """Экран «О колледже»: история и возврат в главное меню колледжа."""
    btns = BUTTONS[lang]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=btns["college_history"], callback_data=f"{CallbackData.COLL_HIST_PREFIX}0"))
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def get_staff_cabinet_kb(
    lang: str,
    *,
    show_review: bool,
    show_staff_scope_tools: bool = False,
    show_targeted_broadcast: bool = False,
    back_callback: str,
) -> InlineKeyboardMarkup:
    """Инлайн-действия личного кабинета для зарегистрированных сотрудников (модерация, рассылки, дорожная карта)."""
    builder = InlineKeyboardBuilder()
    if show_review:
        builder.row(
            InlineKeyboardButton(
                text=BUTTONS[lang]["review_regs"],
                callback_data=CallbackData.REVIEW_REGISTRATIONS,
            )
        )
    if show_targeted_broadcast:
        builder.row(
            InlineKeyboardButton(
                text=tr(lang, "📣 Рассылка по базе (фильтры)", "📣 База бойынша хабарлама (сүзгілер)"),
                callback_data=CallbackData.ADMIN_PANEL_BROADCAST,
            )
        )
    if show_staff_scope_tools:
        builder.row(
            InlineKeyboardButton(
                text=tr(lang, "✉️ Сообщение подопечным", "✉️ Тәлімгерлерге хабарлама"),
                callback_data=CallbackData.STAFF_NOTIFY,
            ),
            InlineKeyboardButton(
                text=tr(lang, "🔄 Сменить группу студенту", "🔄 Студенттің тобын өзгерту"),
                callback_data=CallbackData.STAFF_REASSIGN_START,
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text=tr(
                lang,
                "Рабочее место: расписание и уведомления",
                "Жұмыс орны: кесте және хабарламалар",
            ),
            callback_data=CallbackData.CABINET_WORKPLACE,
        )
    )
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def get_faculties_kb(
    lang: str,
    prefix: str = CallbackData.FAC_PREFIX,
    back_callback: str = CallbackData.LEVEL_UNI,
    track: str = "uni",
) -> InlineKeyboardMarkup:
    """Клавиатура выбора кафедры / бірлестік (для колледжа — объединения по направлениям)."""
    builder = InlineKeyboardBuilder()
    faculties = list(get_specialties_by_department(lang, track).keys())
    for idx, faculty in enumerate(faculties):
        builder.row(InlineKeyboardButton(text=faculty, callback_data=f"{prefix}{idx}"))
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def get_specialties_kb(lang: str, faculty_idx: int, track: str = "uni") -> InlineKeyboardMarkup:
    """Клавиатура выбора специальности (первая страница; листание — через specpg_ / doc_spg_ / calc_spg_)."""
    return get_specialties_paged_kb(
        lang,
        faculty_idx,
        track,
        0,
        spec_prefix=CallbackData.SPEC_PREFIX,
        page_prefix=CallbackData.SPEC_PAGE_PREFIX,
        back_callback=CallbackData.BACK_TO_FACULTY,
    )

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


def get_group_select_kb(lang: str, groups: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group_name in groups[:20]:
        builder.row(
            InlineKeyboardButton(
                text=group_name,
                callback_data=f"{CallbackData.GROUP_PICK_PREFIX}{group_name}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="✍️ Ввести вручную" if lang == "ru" else "✍️ Қолмен енгізу",
            callback_data=CallbackData.GROUP_MANUAL,
        )
    )
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
    builder.row(get_back_button(CallbackData.REG_BACK_PHONE, lang))
    return builder.as_markup()

def get_socials_kb(lang: str, back_callback: str = CallbackData.LEVEL_UNI, track: str = "uni") -> InlineKeyboardMarkup:
    """Клавиатура со ссылками на соцсети."""
    builder = InlineKeyboardBuilder()
    if track == "college":
        builder.row(InlineKeyboardButton(text="📸 Instagram", url="https://www.instagram.com/kzo_college/"))
        builder.row(InlineKeyboardButton(text="✈️ Telegram", url="https://t.me/kzo_college_bot"))
        builder.row(InlineKeyboardButton(text="👤 Facebook", url="https://www.facebook.com/kzo.college/?locale=is_IS"))
        builder.row(InlineKeyboardButton(text="🟦 VK", url="https://vk.com/kkgtkagti?ysclid=mou7i2b188415457684"))
        builder.row(InlineKeyboardButton(text="🌐 Сайт", url="https://kvmk.kz/"))
        builder.row(InlineKeyboardButton(text="🎵 TikTok", url="https://www.tiktok.com/@kzo_college"))
    else:
        builder.row(InlineKeyboardButton(text="📸 Instagram", url="https://www.instagram.com/ashyk_university/"))
        builder.row(InlineKeyboardButton(text="👤 FaceBook", url="https://www.facebook.com/AshykUniversity/"))
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()

def get_location_kb(lang: str, back_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    """Клавиатура с картой и ссылкой на локацию."""
    btns = BUTTONS[lang]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=btns["map"], url="https://go.2gis.com/tYltw"))
    builder.row(get_back_button(back_callback, lang))
    return builder.as_markup()


def get_help_menu_kb(lang: str, back_callback: str = CallbackData.LEVEL_UNI, track: str = "uni") -> InlineKeyboardMarkup:
    """Раздел помощи в виде компактного меню."""
    builder = InlineKeyboardBuilder()
    if lang == "ru":
        buttons = [
            ("🛠 Техническая поддержка", "tech"),
            ("🧠 Психологическая поддержка", "psy"),
            ("🎓 Вопрос колледжу" if track == "college" else "🎓 Вопрос университету", "uni"),
            ("📘 Жалобы и предложения", "book"),
        ]
    else:
        buttons = [
            ("🛠 Техникалық қолдау", "tech"),
            ("🧠 Психологиялық қолдау", "psy"),
            ("🎓 Колледжге сұрақ" if track == "college" else "🎓 Университетке сұрақ", "uni"),
            ("📘 Шағымдар мен ұсыныстар", "book"),
        ]

    for text, code in buttons:
        builder.row(InlineKeyboardButton(text=text, callback_data=f"{CallbackData.HELP_PREFIX}{code}"))
    builder.row(
        InlineKeyboardButton(
            text="🔙 Назад" if lang == "ru" else "🔙 Артқа",
            callback_data=back_callback,
        )
    )
    return builder.as_markup()


def get_rector_blog_kb(lang: str, back_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔗 Блог ректора" if lang == "ru" else "🔗 Ректор блогы",
            url="https://ouk.edu.kz/ru/blog-rektora",
        )
    )
    builder.row(get_back_button(back_callback, lang))
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


def get_psy_ticket_kb(ticket_id: str, lang: str, menu_callback: str = CallbackData.LEVEL_UNI) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    safe_ticket_id = _digits(ticket_id)
    builder.row(
        InlineKeyboardButton(
            text="🏠 В главное меню" if lang == "ru" else "🏠 Бас мәзірге",
            callback_data=menu_callback,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Закрыть тикет" if lang == "ru" else "✅ Тикетті жабу",
            callback_data=f"{CallbackData.PSY_CLOSE_PREFIX}{safe_ticket_id}",
        )
    )
    return builder.as_markup()


def get_psy_rating_kb(ticket_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    safe_ticket_id = _digits(ticket_id)
    for value in range(1, 11):
        builder.button(text=str(value), callback_data=f"{CallbackData.PSY_RATE_PREFIX}{safe_ticket_id}_{value}")
    builder.adjust(5)
    return builder.as_markup()


def get_psy_staff_ticket_kb(ticket_id: str, actor_id: str, *, anonymous: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    safe_ticket_id = _digits(ticket_id)
    builder.row(
        InlineKeyboardButton(text="🚫 Блок 24ч", callback_data=f"{CallbackData.SUPPORT_BLOCK_PREFIX}{safe_ticket_id}_24h"),
        InlineKeyboardButton(text="⛔ Блок навсегда", callback_data=f"{CallbackData.SUPPORT_BLOCK_PREFIX}{safe_ticket_id}_forever"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить сообщения тикета", callback_data=f"{CallbackData.SUPPORT_DELETE_PREFIX}{safe_ticket_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🧑‍⚕️ Назначить психолога", callback_data=f"{CallbackData.SUPPORT_ASSIGN_PREFIX}{safe_ticket_id}")
    )
    return builder.as_markup()


def get_support_confirm_kb(action: str, payload: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if action == "block":
        # Нужно сохранить режим (24h/forever), иначе подтверждение не поймет что блокировать.
        raw = str(payload or "")
        match = re.search(r"(\d+)\s*_(24h|forever)", raw)
        safe_payload = f"{match.group(1)}_{match.group(2)}" if match else raw
    else:
        safe_payload = _digits(payload)
    prefix = (
        CallbackData.SUPPORT_BLOCK_CONFIRM_PREFIX
        if action == "block"
        else CallbackData.SUPPORT_UNBLOCK_CONFIRM_PREFIX
        if action == "unblock"
        else CallbackData.SUPPORT_DELETE_CONFIRM_PREFIX
    )
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{prefix}yes_{safe_payload}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"{prefix}no_{safe_payload}"),
    )
    return builder.as_markup()


def get_psy_stats_period_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="День", callback_data=f"{CallbackData.PSY_STATS_PREFIX}day"),
        InlineKeyboardButton(text="Неделя", callback_data=f"{CallbackData.PSY_STATS_PREFIX}week"),
    )
    builder.row(
        InlineKeyboardButton(text="Месяц", callback_data=f"{CallbackData.PSY_STATS_PREFIX}month"),
        InlineKeyboardButton(text="Год", callback_data=f"{CallbackData.PSY_STATS_PREFIX}year"),
    )
    builder.row(InlineKeyboardButton(text="Все время", callback_data=f"{CallbackData.PSY_STATS_PREFIX}all"))
    return builder.as_markup()
