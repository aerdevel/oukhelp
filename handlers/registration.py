import logging
from math import ceil

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.resources.text_file.catalog import get_specialties_by_department
from core.curator_const import is_responsible_user
from services.access_control import (
    can_review,
    can_use_targeted_broadcast,
    get_all_faculties,
    get_all_specialties,
    get_user_permissions,
    is_admin,
    list_managers,
    set_user_permissions,
)
from states.states import AdminPanel, Form
from keyboards import inline as ikb
from keyboards import reply as rkb
from services.notifier import notify_responsible_new_registration
from services.audit_log import append_audit_event
from services.excel_registry import upsert_registration_account_record
from services.registration_store import (
    add_pending_registration,
    approve_registration,
    deny_registration,
    find_phone_owner,
    get_approved_user,
    get_pending_all,
    get_pending_by_tg_user_id,
    get_processed_all,
    get_approved_all,
)
from utils.i18n import tr
from utils.validators import MIN_FIO_LEN, MIN_GROUP_NAME_LEN, normalize_phone, sanitize_text, validate_min_plaintext
from services.study_groups import (
    add_group,
    delete_group,
    list_all_groups,
    list_groups,
    list_groups_detailed,
    list_groups_for_specialties,
    update_group_name,
)

router = Router()
PAGE_SIZE = 6
ADMIN_SPECS_PAGE_SIZE = 7
ADMIN_SPECS_SELECTED_KEY = "admin_specs_selected"
ADMIN_SPECS_TRACK_KEY = "admin_specs_track"
ADMIN_GROUPS_PAGE_SIZE = 7
ADMIN_GROUPS_SELECTED_KEY = "admin_groups_selected"
ADMIN_GROUPS_TRACK_KEY = "admin_groups_track"
ADMIN_GROUP_MGMT_CTX_KEY = "admin_group_mgmt_ctx"
ROLE_BY_CALLBACK = {
    "role_student": "Студент",
    "role_graduate": "Выпускник",
    "role_worker": "Работник",
    "role_teacher": "Преподаватель",
}


def _track_from_state(data: dict) -> str:
    return "college" if data.get("admission_track") == "college" or data.get("current_choice") == "Колледж" else "uni"


def _safe_tg_id(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def _send_preview(target: types.Message | types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    lang = user_data.get("locale", "ru")
    role = user_data.get("role", "-")
    preview = tr(lang, "📋 Проверьте ваши данные:\n\n", "📋 Мәліметтеріңізді тексеріңіз:\n\n")
    lines = [
        f"👤 ФИО: {user_data.get('fio', '-')}",
        f"📞 Тел: {user_data.get('phone', '-')}",
        f"🎭 Статус: {role}",
    ]
    if user_data.get("faculty"):
        fac_label = (
            tr(lang, "🏛 Бірлестік / объединение:", "🏛 Бірлестік:")
            if _track_from_state(user_data) == "college"
            else tr(lang, "🏛 Кафедра:", "🏛 Кафедра:")
        )
        lines.append(f"{fac_label} {user_data.get('faculty', '-')}")
    if user_data.get("specialty"):
        lines.append(f"📖 Спец: {user_data.get('specialty', '-')}")
    if role in {"Студент", "Выпускник", "Преподаватель"}:
        lines.append(f"📚 Группа: {user_data.get('group', '-')}")
    if role == "Студент":
        lines.append(f"🎓 Курс: {user_data.get('course', '-')}")

    kb = ikb.get_registration_confirm_kb(lang)
    text = preview + "\n".join(lines)
    if isinstance(target, types.Message):
        await target.answer(text, reply_markup=kb)
    else:
        await target.message.edit_text(text, reply_markup=kb)


def _review_page_payload(items: list[dict], page: int) -> tuple[list[dict], int, int]:
    total_pages = max(1, ceil(len(items) / PAGE_SIZE))
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * PAGE_SIZE
    end = start + PAGE_SIZE
    return items[start:end], safe_page, total_pages


def _filter_pending_for_reviewer(user_id: int) -> list[dict]:
    all_pending = get_pending_all()
    if is_admin(user_id):
        return all_pending
    return [item for item in all_pending if can_review(user_id, item.get("group", "-"), item.get("specialty", "-"))]


def _filter_processed_for_reviewer(user_id: int) -> list[dict]:
    all_processed = get_processed_all()
    if is_admin(user_id):
        return all_processed
    return [item for item in all_processed if can_review(user_id, item.get("group", "-"), item.get("specialty", "-"))]


def _admin_candidates() -> list[tuple[int, str]]:
    approved = get_approved_all()
    managers = list_managers()
    items: dict[int, str] = {}
    for row in approved:
        user_id = row.get("tg_user_id")
        if not user_id:
            continue
        display_name = row.get("fio") or row.get("tg_full_name") or f"ID {user_id}"
        items[int(user_id)] = display_name
    for user_id, _ in managers:
        items.setdefault(int(user_id), f"ID {user_id}")
    return sorted(items.items(), key=lambda pair: pair[1].lower())


def _specialties_page_payload(page: int, specialties: list[str]) -> tuple[list[str], int, int]:
    total_pages = max(1, ceil(len(specialties) / ADMIN_SPECS_PAGE_SIZE))
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * ADMIN_SPECS_PAGE_SIZE
    end = start + ADMIN_SPECS_PAGE_SIZE
    return specialties[start:end], safe_page, total_pages


def _get_admin_selected_map(state_data: dict) -> dict[str, list[int]]:
    raw = state_data.get(ADMIN_SPECS_SELECTED_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _selected_for_user(state_data: dict, target_id: int) -> set[int]:
    selected_map = _get_admin_selected_map(state_data)
    return set(selected_map.get(str(target_id), []))


def _get_admin_track_map(state_data: dict) -> dict[str, str]:
    raw = state_data.get(ADMIN_SPECS_TRACK_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _selected_track_for_user(state_data: dict, target_id: int) -> str:
    track = _get_admin_track_map(state_data).get(str(target_id), "uni")
    return "college" if track == "college" else "uni"


def _groups_page_payload(page: int, groups: list[str]) -> tuple[list[str], int, int]:
    total_pages = max(1, ceil(len(groups) / ADMIN_GROUPS_PAGE_SIZE))
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * ADMIN_GROUPS_PAGE_SIZE
    end = start + ADMIN_GROUPS_PAGE_SIZE
    return groups[start:end], safe_page, total_pages


def _get_admin_groups_selected_map(state_data: dict) -> dict[str, list[int]]:
    raw = state_data.get(ADMIN_GROUPS_SELECTED_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _selected_groups_for_user(state_data: dict, target_id: int) -> set[int]:
    selected_map = _get_admin_groups_selected_map(state_data)
    return set(selected_map.get(str(target_id), []))


def _get_admin_groups_track_map(state_data: dict) -> dict[str, str]:
    raw = state_data.get(ADMIN_GROUPS_TRACK_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _selected_groups_track_for_user(state_data: dict, target_id: int) -> str:
    track = _get_admin_groups_track_map(state_data).get(str(target_id), "uni")
    return "college" if track == "college" else "uni"


def _get_group_mgmt_context(state_data: dict) -> dict:
    raw = state_data.get(ADMIN_GROUP_MGMT_CTX_KEY, {})
    return raw if isinstance(raw, dict) else {}


@router.callback_query(F.data == CallbackData.FILL_FORM)
async def start_reg(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    back_callback = CallbackData.LEVEL_COLL if track == "college" else CallbackData.LEVEL_UNI
    text = tr(lang, "🚀 Начнем! Введите ваше ФИО:", "🚀 Бастаймыз! Толық аты-жөніңізді енгізіңіз:")
    await state.update_data(tg_user_id=callback.from_user.id, tg_full_name=callback.from_user.full_name, tg_username=callback.from_user.username)
    if callback.message.text:
        await callback.message.edit_text(text, reply_markup=ikb.get_back_kb(lang, back_callback))
    else:
        await callback.message.answer(text, reply_markup=ikb.get_back_kb(lang, back_callback))
    await state.set_state(Form.fio)
    await callback.answer()


@router.callback_query(F.data == CallbackData.REG_BACK_PHONE)
async def reg_back_to_phone(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    back_menu = CallbackData.LEVEL_COLL if track == "college" else CallbackData.LEVEL_UNI
    await state.update_data(role=None, phone="")
    await state.set_state(Form.phone)
    await callback.message.edit_text(
        tr(
            lang,
            "Отправьте номер телефона (можно кнопкой контакта ниже):",
            "Телефон нөмірін жіберіңіз (төмендегі контакт батырмасын пайдалануға болады):",
        ),
        reply_markup=ikb.get_back_kb(lang, back_menu),
    )
    await callback.message.answer(
        tr(
            lang,
            "Используйте кнопку ниже для отправки контакта или введите номер вручную:",
            "Контактіні жіберу үшін төмендегі батырманы пайдаланыңыз немесе нөмірді қолмен енгізіңіз:",
        ),
        reply_markup=rkb.get_phone_kb(lang),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.REG_BACK_PREVIEW)
async def reg_back_from_preview(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    role = data.get("role")
    if role == "Работник":
        await state.update_data(faculty="-", specialty="-", course="-", group="-")
        await state.set_state(Form.role)
        await callback.message.edit_text(
            tr(lang, "Выберите ваш статус:", "Статусыңызды таңдаңыз:"),
            reply_markup=ikb.get_role_kb(lang),
        )
        await callback.answer()
        return
    if role == "Студент":
        specialty = str(data.get("specialty", "")).strip()
        course = str(data.get("course", "")).strip()
        await state.set_state(Form.group)
        groups = list_groups(track=track, specialty=specialty, course=str(course))
        if groups:
            await callback.message.edit_text(
                tr(
                    lang,
                    "Выберите группу из списка или введите вручную:",
                    "Тізімнен топты таңдаңыз немесе қолмен енгізіңіз:",
                ),
                reply_markup=ikb.get_group_select_kb(lang, groups),
            )
        else:
            await callback.message.edit_text(
                tr(
                    lang,
                    "Введите номер вашей группы (например, ИТ-21-1):",
                    "Топ нөмірін енгізіңіз (мысалы, ИТ-21-1):",
                )
            )
        await callback.answer()
        return
    if role in {"Выпускник", "Преподаватель"}:
        await state.set_state(Form.group)
        await callback.message.edit_text(
            tr(
                lang,
                "Введите номер группы (например, ВТПО 25-1):",
                "Топ нөмірін енгізіңіз (мысалы, ВТПО 25-1):",
            )
        )
        await callback.answer()
        return
    await callback.answer(
        tr(lang, "Вернитесь в меню и начните регистрацию заново.", "Мәзірге оралып, тіркеуді қайта бастаңыз."),
        show_alert=True,
    )


@router.message(Form.fio)
async def process_fio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not message.text:
        await message.answer(tr(lang, "❌ Пожалуйста, отправьте ФИО текстом:", "❌ Аты-жөніңізді мәтінмен жіберіңіз:"))
        return
    normalized_fio = sanitize_text(message.text)
    if not validate_min_plaintext(normalized_fio, min_len=MIN_FIO_LEN):
        await message.answer(tr(lang, "❌ Укажите, пожалуйста, ФИО полностью:", "❌ Толық аты-жөніңізді жазыңыз:"))
        return
    await state.update_data(fio=normalized_fio)
    await message.answer(
        tr(lang, "Приятно познакомиться! Теперь отправьте ваш номер телефона:", "Танысқанымызға қуаныштымын! Енді телефон нөміріңізді жіберіңіз:"),
        reply_markup=rkb.get_phone_kb(lang),
    )
    await state.set_state(Form.phone)


@router.message(Form.phone)
async def process_phone_any(message: types.Message, state: FSMContext):
    # Универсальный обработчик шага телефона: контакт + ручной ввод + Desktop fallback.
    await _process_phone_input(message, state)


async def _process_phone_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    logging.debug(
        "phone_step update: user_id=%s has_contact=%s text=%s",
        message.from_user.id if message.from_user else "-",
        bool(message.contact),
        bool(message.text),
    )
    raw_phone = ""
    if message.contact and message.contact.phone_number:
        if message.contact.user_id and int(message.contact.user_id) != int(message.from_user.id):
            await message.answer(
                tr(
                    lang,
                    "❌ Отправьте, пожалуйста, именно свой контакт через кнопку ниже.",
                    "❌ Төмендегі батырма арқылы өз байланысыңызды жіберіңіз.",
                ),
                reply_markup=rkb.get_phone_kb(lang),
            )
            return
        raw_phone = str(message.contact.phone_number)
    elif message.text:
        raw_phone = str(message.text)

    if raw_phone in {"📱 Отправить контакт", "📱 Контактіні жіберу"}:
        await message.answer(
            tr(
                lang,
                "Если кнопка не отправляет контакт (часто на Desktop), введите номер вручную в формате +7XXXXXXXXXX или 87XXXXXXXXX:",
                "Егер батырма контакт жібермесе (Desktop-та жиі болады), нөмірді +7XXXXXXXXXX немесе 87XXXXXXXXX форматында қолмен енгізіңіз:",
            ),
            reply_markup=rkb.get_phone_kb(lang),
        )
        return

    if not raw_phone:
        await message.answer(
            tr(
                lang,
                "❌ Отправьте номер кнопкой контакта или введите его вручную.",
                "❌ Нөмірді контакт батырмасымен жіберіңіз немесе қолмен енгізіңіз.",
            ),
            reply_markup=rkb.get_phone_kb(lang),
        )
        return
    normalized_phone = normalize_phone(raw_phone)
    if not normalized_phone:
        await message.answer(
            tr(
                lang,
                "❌ Номер распознан некорректно. Пример: +77011234567 или 87011234567.",
                "❌ Нөмір қате танылды. Мысал: +77011234567 немесе 87011234567.",
            )
        )
        return
    owner = find_phone_owner(normalized_phone)
    if owner and _safe_tg_id(owner.get("tg_user_id")) not in {0, _safe_tg_id(message.from_user.id)}:
        await message.answer(
            tr(
                lang,
                "❌ Этот номер уже используется другим пользователем. Укажите свой актуальный номер.",
                "❌ Бұл нөмір басқа пайдаланушыға тиесілі. Өз өзекті нөміріңізді енгізіңіз.",
            ),
            reply_markup=rkb.get_phone_kb(lang),
        )
        return
    await state.update_data(phone=normalized_phone)
    await message.answer(tr(lang, "✅ Номер принят.", "✅ Нөмір қабылданды."), reply_markup=ReplyKeyboardRemove())
    await message.answer(
        tr(
            lang,
            f"Ваш номер сохранен: {normalized_phone}",
            f"Нөміріңіз сақталды: {normalized_phone}",
        )
    )
    try:
        await message.answer(
            tr(lang, "Выберите ваш статус:", "Статусыңызды таңдаңыз:"),
            reply_markup=ikb.get_role_kb(lang),
        )
    except Exception as err:
        logging.warning("Не удалось показать inline-кнопки выбора роли: %s", err)
        await message.answer(
            tr(
                lang,
                "Выберите статус командой:\n"
                "• /student\n"
                "• /graduate\n"
                "• /worker\n"
                "• /teacher",
                "Күйді командамен таңдаңыз:\n"
                "• /student\n"
                "• /graduate\n"
                "• /worker\n"
                "• /teacher",
            )
        )
    await state.set_state(Form.role)


@router.callback_query(Form.role, F.data.in_(list(ROLE_BY_CALLBACK.keys())))
async def process_role(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    role = ROLE_BY_CALLBACK[callback.data]
    await state.update_data(role=role)
    if role == "Работник":
        await state.update_data(faculty="-", specialty="-", course="-", group="-")
        await _send_preview(callback, state)
    else:
        text = (
            tr(lang, "Выберите бірлестік (структурное объединение):", "Бірлестікті таңдаңыз:")
            if track == "college"
            else tr(lang, "Выберите кафедру:", "Кафедраны таңдаңыз:")
        )
        await callback.message.edit_text(text, reply_markup=ikb.get_faculties_kb(lang, track=track))
        await state.set_state(Form.specialty)
    await callback.answer()


@router.message(Form.role, F.text.in_(["/student", "/graduate", "/worker", "/teacher"]))
async def process_role_text_fallback(message: types.Message, state: FSMContext):
    mapping = {
        "/student": "Студент",
        "/graduate": "Выпускник",
        "/worker": "Работник",
        "/teacher": "Преподаватель",
    }
    role = mapping.get((message.text or "").strip().lower())
    if not role:
        return
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    await state.update_data(role=role)
    if role == "Работник":
        await state.update_data(faculty="-", specialty="-", course="-", group="-")
        await _send_preview(message, state)
        return
    await message.answer(
        tr(
            lang,
            "Выберите бірлестік (структурное объединение):"
            if track == "college"
            else "Выберите кафедру:",
            "Бірлестікті таңдаңыз:" if track == "college" else "Кафедраны таңдаңыз:",
        ),
        reply_markup=ikb.get_faculties_kb(lang, track=track),
    )
    await state.set_state(Form.specialty)


@router.callback_query(Form.specialty, F.data.startswith(CallbackData.FAC_PREFIX))
async def process_faculty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    faculty_idx = callback.data.replace(CallbackData.FAC_PREFIX, "")
    faculties = list(get_specialties_by_department(lang, track).keys())
    if not faculty_idx.isdigit() or int(faculty_idx) >= len(faculties):
        await callback.answer("Некорректный выбор кафедры", show_alert=True)
        return
    selected_idx = int(faculty_idx)
    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    selected_faculty = faculties[selected_idx]
    specs = specialties_by_department[selected_faculty]
    total_pages = max(1, ceil(len(specs) / ikb.SPECIALTY_PAGE_SIZE))
    header = ikb.specialty_pick_header(lang, track, selected_faculty, 0, total_pages)
    await callback.message.edit_text(
        header,
        reply_markup=ikb.get_specialties_paged_kb(
            lang,
            selected_idx,
            track,
            0,
            spec_prefix=CallbackData.SPEC_PREFIX,
            page_prefix=CallbackData.SPEC_PAGE_PREFIX,
            back_callback=CallbackData.BACK_TO_FACULTY,
        ),
    )
    await callback.answer()


@router.callback_query(Form.specialty, F.data.startswith(CallbackData.SPEC_PAGE_PREFIX))
async def process_specialty_page(callback: types.CallbackQuery, state: FSMContext):
    """Перелистывание списка специальностей при регистрации."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    payload = callback.data.replace(CallbackData.SPEC_PAGE_PREFIX, "")
    fac_raw, _, page_raw = payload.partition("_")
    if not fac_raw.isdigit() or not page_raw.isdigit():
        await callback.answer(tr(lang, "Некорректная страница.", "Бет дұрыс емес."), show_alert=True)
        return
    fac_idx = int(fac_raw)
    page = int(page_raw)
    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    if fac_idx >= len(faculties):
        await callback.answer(tr(lang, "Некорректная страница.", "Бет дұрыс емес."), show_alert=True)
        return
    selected_faculty = faculties[fac_idx]
    specs = specialties_by_department[selected_faculty]
    total_pages = max(1, ceil(len(specs) / ikb.SPECIALTY_PAGE_SIZE))
    safe_page = max(0, min(page, total_pages - 1))
    header = ikb.specialty_pick_header(lang, track, selected_faculty, safe_page, total_pages)
    await callback.message.edit_text(
        header,
        reply_markup=ikb.get_specialties_paged_kb(
            lang,
            fac_idx,
            track,
            safe_page,
            spec_prefix=CallbackData.SPEC_PREFIX,
            page_prefix=CallbackData.SPEC_PAGE_PREFIX,
            back_callback=CallbackData.BACK_TO_FACULTY,
        ),
    )
    await callback.answer()


@router.callback_query(Form.specialty, F.data.startswith(CallbackData.SPEC_PREFIX))
async def process_specialty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    role = data.get("role")
    payload = callback.data.replace(CallbackData.SPEC_PREFIX, "")
    if "_" not in payload:
        await callback.answer("Некорректный выбор специальности", show_alert=True)
        return
    fac_idx_raw, spec_idx_raw = payload.split("_", 1)
    if not fac_idx_raw.isdigit() or not spec_idx_raw.isdigit():
        await callback.answer("Некорректный выбор специальности", show_alert=True)
        return
    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    fac_idx = int(fac_idx_raw)
    spec_idx = int(spec_idx_raw)
    if fac_idx >= len(faculties):
        await callback.answer("Некорректный выбор специальности", show_alert=True)
        return
    selected_faculty = faculties[fac_idx]
    specialties = specialties_by_department[selected_faculty]
    if spec_idx >= len(specialties):
        await callback.answer("Некорректный выбор специальности", show_alert=True)
        return
    await state.update_data(faculty=selected_faculty, specialty=specialties[spec_idx])
    if role == "Студент":
        await callback.message.edit_text("На каком курсе вы учитесь?" if lang == "ru" else "Қай курста оқисыз?", reply_markup=ikb.get_course_kb(lang))
        await state.set_state(Form.course)
    elif role in {"Выпускник", "Преподаватель"}:
        await state.update_data(course="-")
        await callback.message.edit_text(
            "Введите номер группы (например, ВТПО 25-1):" if lang == "ru" else "Топ нөмірін енгізіңіз (мысалы, ВТПО 25-1):"
        )
        await state.set_state(Form.group)
    else:
        await state.update_data(course="-", group="-")
        await _send_preview(callback, state)
    await callback.answer()


@router.callback_query(F.data == CallbackData.BACK_TO_SPEC)
async def back_to_specialty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    prompt = (
        tr(lang, "Выберите бірлестік (структурное объединение):", "Бірлестікті таңдаңыз:")
        if track == "college"
        else tr(lang, "Выберите кафедру:", "Кафедраны таңдаңыз:")
    )
    await callback.message.edit_text(prompt, reply_markup=ikb.get_faculties_kb(lang, track=track))
    await state.set_state(Form.specialty)
    await callback.answer()


@router.callback_query(F.data == CallbackData.BACK_TO_FACULTY)
async def back_to_faculty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    prompt = (
        tr(lang, "Выберите бірлестік (структурное объединение):", "Бірлестікті таңдаңыз:")
        if track == "college"
        else tr(lang, "Выберите кафедру:", "Кафедраны таңдаңыз:")
    )
    await callback.message.edit_text(prompt, reply_markup=ikb.get_faculties_kb(lang, track=track))
    await state.set_state(Form.specialty)
    await callback.answer()


@router.callback_query(Form.course, F.data.startswith(CallbackData.COURSE_PREFIX))
async def process_course(callback: types.CallbackQuery, state: FSMContext):
    course_val = callback.data.replace(CallbackData.COURSE_PREFIX, "")
    await state.update_data(course=course_val)
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    specialty = str(data.get("specialty", "")).strip()
    groups = list_groups(track=track, specialty=specialty, course=str(course_val))
    if groups:
        await callback.message.edit_text(
            tr(
                lang,
                "Выберите группу из списка или введите вручную:",
                "Тізімнен топты таңдаңыз немесе қолмен енгізіңіз:",
            ),
            reply_markup=ikb.get_group_select_kb(lang, groups),
        )
    else:
        await callback.message.edit_text(
            "Введите номер вашей группы (например, ИТ-21-1):" if lang == "ru" else "Топ нөмірін енгізіңіз (мысалы, ИТ-21-1):"
        )
    await state.set_state(Form.group)
    await callback.answer()


@router.callback_query(Form.group, F.data.startswith(CallbackData.GROUP_PICK_PREFIX))
async def process_group_pick(callback: types.CallbackQuery, state: FSMContext):
    group_name = callback.data.replace(CallbackData.GROUP_PICK_PREFIX, "").strip()
    if not group_name:
        await callback.answer("Некорректная группа.", show_alert=True)
        return
    await state.update_data(group=group_name)
    await _send_preview(callback, state)
    await callback.answer()


@router.callback_query(Form.group, F.data == CallbackData.GROUP_MANUAL)
async def process_group_manual(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await callback.message.edit_text(
        "Введите номер вашей группы (например, ИТ-21-1):" if lang == "ru" else "Топ нөмірін енгізіңіз (мысалы, ИТ-21-1):"
    )
    await callback.answer()


@router.message(Form.group)
async def process_group(message: types.Message, state: FSMContext):
    if not message.text or not message.text.strip():
        user_data = await state.get_data()
        lang = user_data.get("locale", "ru")
        await message.answer("❌ Введите номер группы текстом." if lang == "ru" else "❌ Топ нөмірін мәтінмен енгізіңіз.")
        return
    await state.update_data(group=sanitize_text(message.text))
    await _send_preview(message, state)


@router.callback_query(F.data == CallbackData.CONFIRM_FINAL)
async def confirm_registration(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    lang = user_data.get("locale", "ru")
    user_data["admission_track"] = _track_from_state(user_data)
    user_data.setdefault("is_grant", False)
    add_pending_registration(user_data)
    user_data["status"] = "pending"
    pending_card = get_pending_by_tg_user_id(callback.from_user.id) or {}
    if pending_card:
        user_data["submit_attempt"] = int(pending_card.get("submit_attempt", 1) or 1)
    excel_result = upsert_registration_account_record(user_data)
    user_data["excel_account_saved"] = bool(excel_result.get("ok"))
    user_data["excel_account_was_existing"] = bool(excel_result.get("was_existing"))
    await notify_responsible_new_registration(callback.bot, user_data)
    text = (
        "✅ Заявка отправлена. Ожидайте, с вами свяжется ответственный менеджер."
        if lang == "ru"
        else "✅ Өтінім жіберілді. Жауапты менеджер сізбен байланысады."
    )
    menu_callback = CallbackData.LEVEL_COLL if user_data.get("admission_track") == "college" else CallbackData.LEVEL_UNI
    await callback.message.edit_text(text, reply_markup=ikb.get_back_kb(lang, menu_callback))
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == CallbackData.MY_CABINET)
async def my_cabinet(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    profile = get_approved_user(callback.from_user.id)
    if not profile:
        await callback.answer(tr(lang, "Кабинет доступен после одобрения регистрации.", "Кабинет тіркеу мақұлданғаннан кейін қолжетімді."), show_alert=True)
        return
    text = (
        "🧾 Мой кабинет\n\n"
        f"👤 ФИО: {profile.get('fio', '-')}\n"
        f"📞 Тел: {profile.get('phone', '-')}\n"
        f"🎭 Статус: {profile.get('role', '-')}\n"
        f"🏛 Кафедра: {profile.get('faculty', '-')}\n"
        f"📖 Спец: {profile.get('specialty', '-')}\n"
        f"🎓 Курс: {profile.get('course', '-')}\n"
        f"📚 Группа: {profile.get('group', '-')}"
    )
    menu_callback = CallbackData.LEVEL_COLL if str(profile.get("admission_track", "uni")) == "college" else CallbackData.LEVEL_UNI
    perms = get_user_permissions(callback.from_user.id)
    show_staff_scope = bool(is_admin(callback.from_user.id) or perms.get("can_review"))
    show_targeted_broadcast = bool(can_use_targeted_broadcast(callback.from_user.id) and not is_admin(callback.from_user.id))
    cabinet_markup = ikb.get_staff_cabinet_kb(
        lang,
        show_review=is_responsible_user(callback.from_user.id),
        show_staff_scope_tools=show_staff_scope,
        show_targeted_broadcast=show_targeted_broadcast,
        back_callback=menu_callback,
    )
    await callback.message.edit_text(text, reply_markup=cabinet_markup)
    await callback.answer()


@router.callback_query(F.data == CallbackData.REVIEW_REGISTRATIONS)
async def review_registrations(callback: types.CallbackQuery, state: FSMContext):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    items = _filter_pending_for_reviewer(callback.from_user.id)
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not items:
        await callback.message.edit_text(
            tr(lang, "Сейчас нет необработанных заявок.", "Қазір өңделмеген өтінім жоқ."),
            reply_markup=ikb.get_review_list_kb([], 0, 1, processed=False),
        )
        await callback.answer()
        return
    page_items, page, total_pages = _review_page_payload(items, 0)
    await callback.message.edit_text(
        tr(lang, "🛂 Центр модерации: необработанные", "🛂 Модерация орталығы: өңделмеген"),
        reply_markup=ikb.get_review_list_kb(page_items, page, total_pages, processed=False),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.REVIEW_PAGE_PREFIX))
async def review_page(callback: types.CallbackQuery):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.REVIEW_PAGE_PREFIX, "")
    processed_raw, _, page_raw = payload.partition("_")
    processed = processed_raw == "1"
    page = int(page_raw) if page_raw.isdigit() else 0
    items = _filter_processed_for_reviewer(callback.from_user.id) if processed else _filter_pending_for_reviewer(callback.from_user.id)
    if not items:
        await callback.answer("Список пуст.", show_alert=True)
        return
    page_items, safe_page, total_pages = _review_page_payload(items, page)
    await callback.message.edit_reply_markup(
        reply_markup=ikb.get_review_list_kb(page_items, safe_page, total_pages, processed=processed)
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.REVIEW_OPEN_PREFIX))
async def review_open(callback: types.CallbackQuery, state: FSMContext):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    tg_user_id_raw = callback.data.replace(CallbackData.REVIEW_OPEN_PREFIX, "")
    if not tg_user_id_raw.isdigit():
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    tg_user_id = int(tg_user_id_raw)
    card = get_pending_by_tg_user_id(tg_user_id)
    if not card:
        await callback.answer("Заявка уже обработана. Откройте вкладку обработанных.", show_alert=True)
        return
    if not is_admin(callback.from_user.id) and not can_review(
        callback.from_user.id,
        card.get("group", "-"),
        card.get("specialty", "-"),
    ):
        await callback.answer("Нет доступа к этой группе.", show_alert=True)
        return
    username_text = f"@{card.get('tg_username')}" if card.get("tg_username") else "-"
    track_label = "Колледж" if str(card.get("admission_track", "uni")) == "college" else "Университет"
    text = (
        "📋 Данные заявки\n\n"
        f"🎓 Уровень: {track_label}\n"
        f"👤 ФИО: {card.get('fio', '-')}\n"
        f"📞 Тел: {card.get('phone', '-')}\n"
        f"🎭 Статус: {card.get('role', '-')}\n"
        f"🏛 Кафедра: {card.get('faculty', '-')}\n"
        f"📖 Спец: {card.get('specialty', '-')}\n"
        f"🎓 Курс: {card.get('course', '-')}\n"
        f"📚 Группа: {card.get('group', '-')}\n"
        f"👤 Telegram: {card.get('tg_full_name', '-')}\n"
        f"🆔 Telegram ID: {card.get('tg_user_id', '-')}\n"
        f"🔗 Username: {username_text}"
    )
    await callback.message.edit_text(text, reply_markup=ikb.get_review_actions_kb(tg_user_id))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.REVIEW_ACTION_PREFIX))
@router.callback_query(F.data.startswith("reg_"))
async def review_action(callback: types.CallbackQuery, state: FSMContext):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    data = await state.get_data()
    lang = data.get("locale", "ru")
    raw = callback.data.replace(CallbackData.REVIEW_ACTION_PREFIX, "")
    if callback.data.startswith("reg_approve_"):
        raw = f"approve_{callback.data.replace('reg_approve_', '')}"
    elif callback.data.startswith("reg_deny_"):
        raw = f"deny_{callback.data.replace('reg_deny_', '')}"
    action, _, phone = raw.partition("_")
    target_user_id: int | None = None
    if callback.data.startswith(CallbackData.REVIEW_ACTION_PREFIX):
        # Новый формат: review_action_<action>_<tg_user_id>
        if phone.isdigit():
            target_user_id = int(phone)
    if target_user_id is None:
        # Legacy формат: review_action/reg_*_<phone>
        if not phone:
            await callback.answer("Некорректная заявка.", show_alert=True)
            return
        pending = [item for item in get_pending_all() if item.get("phone") == phone]
        if len(pending) > 1:
            await callback.answer("Найдено несколько заявок с этим телефоном. Откройте карточку через список.", show_alert=True)
            return
        target_user_id = int(pending[0].get("tg_user_id")) if pending else None
    if target_user_id is None:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    card = get_pending_by_tg_user_id(target_user_id)
    if not card:
        await callback.answer("Заявка уже обработана. Откройте вкладку обработанных.", show_alert=True)
        return
    if (not is_admin(callback.from_user.id)) and (not can_review(callback.from_user.id, card.get("group", "-"), card.get("specialty", "-"))):
        await callback.answer("Нет доступа к этой группе.", show_alert=True)
        return
    phone_value = str(card.get("phone", ""))
    if action == "approve":
        approved = approve_registration(phone_value, callback.from_user.id, callback.from_user.username)
        if not approved:
            await callback.answer("Заявка уже обработана.", show_alert=True)
            return
        upsert_registration_account_record(approved)
        try:
            await callback.bot.send_message(int(approved.get("tg_user_id")), tr(lang, "✅ Ваша регистрация одобрена. Теперь доступен раздел «Мой кабинет».", "✅ Тіркелуіңіз мақұлданды. Енді «Жеке кабинет» бөлімі қолжетімді."))
        except Exception as err:
            logging.warning("Не удалось уведомить пользователя %s об одобрении регистрации: %s", approved.get("tg_user_id"), err)
        append_audit_event(
            "registration_approved",
            callback.from_user.id,
            {"phone": phone_value, "tg_user_id": approved.get("tg_user_id")},
        )
        await callback.message.edit_text("✅ Заявка одобрена.")
    elif action == "deny":
        denied = deny_registration(phone_value, callback.from_user.id, callback.from_user.username)
        if not denied:
            await callback.answer("Заявка уже обработана.", show_alert=True)
            return
        upsert_registration_account_record(denied)
        try:
            await callback.bot.send_message(int(denied.get("tg_user_id")), tr(lang, "❌ Заявка отклонена. Пожалуйста, заполните анкету повторно.", "❌ Өтінім қабылданбады. Анкетаны қайта толтырыңыз."))
        except Exception as err:
            logging.warning("Не удалось уведомить пользователя %s об отклонении регистрации: %s", denied.get("tg_user_id"), err)
        append_audit_event(
            "registration_denied",
            callback.from_user.id,
            {"phone": phone_value, "tg_user_id": denied.get("tg_user_id")},
        )
        await callback.message.edit_text("❌ Заявка отклонена.")
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.REVIEW_DONE_OPEN_PREFIX))
async def review_done_open(callback: types.CallbackQuery):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    tg_user_id_raw = callback.data.replace(CallbackData.REVIEW_DONE_OPEN_PREFIX, "")
    if not tg_user_id_raw.isdigit():
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    tg_user_id = int(tg_user_id_raw)
    card = next((row for row in _filter_processed_for_reviewer(callback.from_user.id) if int(row.get("tg_user_id", 0)) == tg_user_id), None)
    if not card:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    reviewer_username = str(card.get("reviewed_by_username", "")).strip()
    reviewer_info = f"@{reviewer_username}" if reviewer_username else str(card.get("reviewed_by", "-"))
    track_label = "Колледж" if str(card.get("admission_track", "uni")) == "college" else "Университет"
    text = (
        "✅ Обработанная заявка\n\n"
        f"🎓 Уровень: {track_label}\n"
        f"👤 ФИО: {card.get('fio', '-')}\n"
        f"📚 Группа: {card.get('group', '-')}\n"
        f"📌 Статус: {card.get('status', '-')}\n"
        f"👨‍💼 Обработал: {reviewer_info}\n"
        f"🕒 Время: {card.get('reviewed_at', '-')}"
    )
    await callback.message.edit_text(text, reply_markup=ikb.get_back_kb("ru", f"{CallbackData.REVIEW_TAB_PREFIX}1"))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.REVIEW_TAB_PREFIX))
async def review_tab(callback: types.CallbackQuery, state: FSMContext):
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    data = await state.get_data()
    lang = data.get("locale", "ru")
    tab_raw = callback.data.replace(CallbackData.REVIEW_TAB_PREFIX, "")
    processed = tab_raw == "1"
    items = _filter_processed_for_reviewer(callback.from_user.id) if processed else _filter_pending_for_reviewer(callback.from_user.id)
    page_items, page, total_pages = _review_page_payload(items, 0)
    title = tr(lang, "✅ Обработанные заявки" if processed else "⏳ Необработанные заявки", "✅ Өңделген өтінімдер" if processed else "⏳ Өңделмеген өтінімдер")
    await callback.message.edit_text(title, reply_markup=ikb.get_review_list_kb(page_items, page, total_pages, processed=processed))
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: types.CallbackQuery):
    await callback.answer()


@router.message(F.text.in_(["🧾 Мой кабинет", "🧾 Жеке кабинет"]))
async def my_cabinet_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    profile = get_approved_user(message.from_user.id)
    if not profile:
        await message.answer(tr(lang, "Кабинет доступен после одобрения регистрации.", "Кабинет тіркеу мақұлданғаннан кейін қолжетімді."))
        return
    await message.answer(
        "🧾 Мой кабинет\n\n"
        f"👤 ФИО: {profile.get('fio', '-')}\n"
        f"📞 Тел: {profile.get('phone', '-')}\n"
        f"🎭 Статус: {profile.get('role', '-')}\n"
        f"🏛 Кафедра: {profile.get('faculty', '-')}\n"
        f"📖 Спец: {profile.get('specialty', '-')}\n"
        f"🎓 Курс: {profile.get('course', '-')}\n"
        f"📚 Группа: {profile.get('group', '-')}"
    )


@router.message(F.text.in_(["🛂 Центр модерации", "🛂 Модерация орталығы"]))
async def review_registrations_text(message: types.Message, state: FSMContext):
    if not is_responsible_user(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    data = await state.get_data()
    lang = data.get("locale", "ru")
    items = _filter_pending_for_reviewer(message.from_user.id)
    if not items:
        await message.answer(tr(lang, "Сейчас нет необработанных заявок.", "Қазір өңделмеген өтінім жоқ."), reply_markup=ikb.get_review_list_kb([], 0, 1, processed=False))
        return
    page_items, page, total_pages = _review_page_payload(items, 0)
    await message.answer(
        tr(lang, "🛂 Центр модерации: необработанные", "🛂 Модерация орталығы: өңделмеген"),
        reply_markup=ikb.get_review_list_kb(page_items, page, total_pages, processed=False),
    )


@router.message(F.text.in_(["⚙️ Управление доступами", "⚙️ Қолжетімділікті басқару"]))
async def admin_access_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    items = _admin_candidates()
    if not items:
        await message.answer("Пока нет назначенных пользователей.")
        return
    await message.answer("⚙️ Выберите пользователя для изменения прав:", reply_markup=ikb.get_admin_users_kb(items))


@router.message(F.text.in_(["🛠 Админ панель", "🛠 Админ панелі"]))
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await state.set_state(None)
    await message.answer("🛠 Админ-панель", reply_markup=ikb.get_admin_panel_kb())


@router.callback_query(F.data == CallbackData.ADMIN_PANEL)
async def admin_panel_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(None)
    await callback.message.edit_text("🛠 Админ-панель", reply_markup=ikb.get_admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_PANEL_REVIEW)
async def admin_panel_review(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    items = _filter_pending_for_reviewer(callback.from_user.id)
    if not items:
        await callback.message.edit_text(
            "Сейчас нет необработанных заявок.",
            reply_markup=ikb.get_review_list_kb([], 0, 1, processed=False),
        )
        await callback.answer()
        return
    page_items, page, total_pages = _review_page_payload(items, 0)
    await callback.message.edit_text(
        "🛂 Центр модерации: необработанные",
        reply_markup=ikb.get_review_list_kb(page_items, page, total_pages, processed=False),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_PANEL_ACCESS)
async def admin_panel_access(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    items = _admin_candidates()
    if not items:
        await callback.message.edit_text("Пока нет назначенных пользователей.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "⚙️ Выберите пользователя для изменения прав:",
        reply_markup=ikb.get_admin_users_kb(items),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_PANEL_CREATE_GROUP)
async def admin_panel_create_group(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {"action": "create"}})
    await callback.message.edit_text(
        "Создание группы: выберите уровень",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="🏛 Университет", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX}uni"),
                    types.InlineKeyboardButton(text="🏫 Колледж", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX}college"),
                ],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data=CallbackData.ADMIN_PANEL)],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_PANEL_GROUPS)
async def admin_panel_groups(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {}})
    await callback.message.edit_text(
        "🗂 Управление группами: выберите уровень",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="🏛 Университет", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX}uni"),
                    types.InlineKeyboardButton(text="🏫 Колледж", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX}college"),
                ],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data=CallbackData.ADMIN_PANEL)],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX))
async def admin_group_mgmt_track(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    track = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX, "")
    if track not in {"uni", "college"}:
        await callback.answer("Некорректный уровень.", show_alert=True)
        return
    faculties = list(get_specialties_by_department("ru", track).keys())
    builder = InlineKeyboardBuilder()
    for idx, faculty in enumerate(faculties):
        builder.row(types.InlineKeyboardButton(text=faculty, callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_FAC_PREFIX}{idx}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CallbackData.ADMIN_PANEL_GROUPS))
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {"track": track}})
    title = "Выберите бірлестік (структурное объединение):" if track == "college" else "Выберите кафедру:"
    await callback.message.edit_text(title, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_FAC_PREFIX))
async def admin_group_mgmt_fac(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    track = ctx.get("track", "uni")
    raw = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_FAC_PREFIX, "")
    faculties = list(get_specialties_by_department("ru", track).keys())
    if not raw.isdigit() or int(raw) >= len(faculties):
        await callback.answer(
            "Некорректное объединение." if track == "college" else "Некорректная кафедра.",
            show_alert=True,
        )
        return
    faculty_idx = int(raw)
    faculty = faculties[faculty_idx]
    specs = get_specialties_by_department("ru", track).get(faculty, [])
    builder = InlineKeyboardBuilder()
    for idx, spec in enumerate(specs):
        builder.row(types.InlineKeyboardButton(text=spec, callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_SPEC_PREFIX}{idx}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_TRACK_PREFIX}{track}"))
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {**ctx, "faculty": faculty, "faculty_idx": faculty_idx}})
    await callback.message.edit_text("Выберите специальность:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_SPEC_PREFIX))
async def admin_group_mgmt_spec(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    track = ctx.get("track", "uni")
    faculty = ctx.get("faculty", "")
    specs = get_specialties_by_department("ru", track).get(faculty, [])
    raw = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_SPEC_PREFIX, "")
    if not raw.isdigit() or int(raw) >= len(specs):
        await callback.answer("Некорректная специальность.", show_alert=True)
        return
    spec_idx = int(raw)
    specialty = specs[spec_idx]
    builder = InlineKeyboardBuilder()
    for course in ["1", "2", "3", "4", "Graduate"]:
        label = f"{course} курс" if course != "Graduate" else "Выпускник"
        builder.row(types.InlineKeyboardButton(text=label, callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_COURSE_PREFIX}{course}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_FAC_PREFIX}{int(ctx.get('faculty_idx', 0))}"))
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {**ctx, "specialty": specialty, "spec_idx": spec_idx}})
    await callback.message.edit_text("Выберите курс:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_COURSE_PREFIX))
async def admin_group_mgmt_course(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    course = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_COURSE_PREFIX, "")
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    track = ctx.get("track", "uni")
    faculty = ctx.get("faculty", "")
    specialty = ctx.get("specialty", "")
    rows = list_groups_detailed(track=track, faculty=faculty, specialty=specialty, course=course)
    if str(ctx.get("action", "")) == "create":
        await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {**ctx, "course": course}})
        await state.set_state(AdminPanel.waiting_for_group_name)
        await callback.message.edit_text(
            f"Вы выбрали: {track} / {faculty} / {specialty} / {course}\nВведите название новой группы:"
        )
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for row in rows[:25]:
        builder.row(
            types.InlineKeyboardButton(
                text=row["group_name"],
                callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_OPEN_PREFIX}{row['group_name']}",
            )
        )
    builder.row(types.InlineKeyboardButton(text="➕ Создать группу", callback_data=CallbackData.ADMIN_GROUP_MGMT_CREATE))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_SPEC_PREFIX}{int(ctx.get('spec_idx', 0))}"))
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {**ctx, "course": course}})
    await callback.message.edit_text(
        f"Группы: {faculty} / {specialty} / {course}\nВыберите группу для действий:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_GROUP_MGMT_CREATE)
async def admin_group_mgmt_create(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.waiting_for_group_name)
    await callback.message.answer("Введите название новой группы:")
    await callback.answer()


@router.message(AdminPanel.waiting_for_group_name)
async def admin_group_mgmt_create_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        await state.set_state(None)
        return
    name = sanitize_text(message.text or "")
    if not validate_min_plaintext(name, min_len=MIN_GROUP_NAME_LEN):
        await message.answer("Название группы слишком короткое.")
        return
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    ok = add_group(
        track=ctx.get("track", "uni"),
        faculty=ctx.get("faculty", ""),
        specialty=ctx.get("specialty", ""),
        course=ctx.get("course", ""),
        group_name=name,
        created_by=message.from_user.id,
    )
    await state.set_state(None)
    if not ok:
        await message.answer("Не удалось создать группу (возможно дубликат).")
        return
    await message.answer("✅ Группа создана.", reply_markup=ikb.get_admin_panel_kb())


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_OPEN_PREFIX))
async def admin_group_mgmt_open(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    group_name = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_OPEN_PREFIX, "")
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    await state.update_data(**{ADMIN_GROUP_MGMT_CTX_KEY: {**ctx, "group_name": group_name}})
    await callback.message.edit_text(
        f"Группа: {group_name}\nВыберите действие:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="✏️ Переименовать", callback_data=CallbackData.ADMIN_GROUP_MGMT_RENAME)],
                [types.InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_ACTION_PREFIX}delete")],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"{CallbackData.ADMIN_GROUP_MGMT_COURSE_PREFIX}{ctx.get('course', '1')}")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == CallbackData.ADMIN_GROUP_MGMT_RENAME)
async def admin_group_mgmt_rename(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminPanel.waiting_for_group_rename)
    await callback.message.answer("Введите новое название группы:")
    await callback.answer()


@router.message(AdminPanel.waiting_for_group_rename)
async def admin_group_mgmt_rename_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        await state.set_state(None)
        return
    new_name = sanitize_text(message.text or "")
    if not validate_min_plaintext(new_name, min_len=MIN_GROUP_NAME_LEN):
        await message.answer("Название группы слишком короткое.")
        return
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    ok = update_group_name(
        track=ctx.get("track", "uni"),
        faculty=ctx.get("faculty", ""),
        specialty=ctx.get("specialty", ""),
        course=ctx.get("course", ""),
        old_group_name=ctx.get("group_name", ""),
        new_group_name=new_name,
    )
    await state.set_state(None)
    if not ok:
        await message.answer("Не удалось переименовать группу.")
        return
    await message.answer("✅ Группа переименована.", reply_markup=ikb.get_admin_panel_kb())


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUP_MGMT_ACTION_PREFIX))
async def admin_group_mgmt_action(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    action = callback.data.replace(CallbackData.ADMIN_GROUP_MGMT_ACTION_PREFIX, "")
    if action != "delete":
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    state_data = await state.get_data()
    ctx = _get_group_mgmt_context(state_data)
    ok = delete_group(
        track=ctx.get("track", "uni"),
        faculty=ctx.get("faculty", ""),
        specialty=ctx.get("specialty", ""),
        course=ctx.get("course", ""),
        group_name=ctx.get("group_name", ""),
    )
    if not ok:
        await callback.answer("Не удалось удалить группу.", show_alert=True)
        return
    await callback.message.edit_text("✅ Группа удалена.", reply_markup=ikb.get_admin_panel_kb())
    await callback.answer()


@router.message(AdminPanel.waiting_for_group_payload)
async def admin_panel_create_group_payload(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        await state.set_state(None)
        return
    raw = (message.text or "").strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 5 or parts[0] not in {"uni", "college"}:
        await message.answer("Некорректный формат. Ожидается: <uni|college>|<кафедра>|<спец>|<курс>|<группа>")
        return
    track, faculty, specialty, course, group_name = parts
    ok = add_group(
        track=track,
        faculty=faculty,
        specialty=specialty,
        course=course,
        group_name=group_name,
        created_by=message.from_user.id,
    )
    if not ok:
        await message.answer("Не удалось создать группу (возможно, дубликат или пустые поля).")
        return
    await state.set_state(None)
    await message.answer(f"✅ Группа добавлена: {group_name} ({specialty}, курс {course}, {track}).", reply_markup=ikb.get_admin_panel_kb())


@router.callback_query(F.data.startswith(CallbackData.ADMIN_USER_PREFIX))
async def admin_open_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_USER_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    profile = get_user_permissions(target_id)
    groups = ", ".join(profile["groups"]) if profile["groups"] else "-"
    specialties = ", ".join(profile["specialties"]) if profile["specialties"] else "-"
    faculties = ", ".join(profile.get("faculties", [])) if profile.get("faculties") else "-"
    approved = get_approved_user(target_id) or {}
    username = approved.get("tg_username")
    username_text = f"@{username}" if username else "-"
    text = (
        f"👤 Пользователь: {approved.get('fio', '-')}\n"
        f"🆔 Telegram ID: {target_id}\n"
        f"🔗 Username: {username_text}\n"
        f"🔔 Уведомления: {'Да' if profile['can_notify'] else 'Нет'}\n"
        f"✅ Модерация: {'Да' if profile['can_review'] else 'Нет'}\n"
        f"👑 Админ: {'Да' if profile['is_admin'] else 'Нет'}\n"
        f"🏛 Кафедры: {faculties}\n"
        f"📚 Группы: {groups}\n\n"
        f"🎓 Специальности: {specialties}\n\n"
        "Выберите действие ниже."
    )
    profile_view = dict(profile)
    profile_view["is_grant"] = bool(approved.get("is_grant"))
    await callback.message.edit_text(text, reply_markup=ikb.get_admin_user_actions_kb(target_id, profile_view))
    await callback.answer()


@router.callback_query(F.data == "admin_back_list")
async def admin_back_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.message.edit_text("⚙️ Выберите пользователя для изменения прав:", reply_markup=ikb.get_admin_users_kb(_admin_candidates()))
    await callback.answer()


async def _toggle_permission(callback: types.CallbackQuery, prefix: str, field: str):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(prefix, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    current = get_user_permissions(target_id)
    kwargs = {
        "can_notify": current["can_notify"],
        "can_review": current["can_review"],
        "can_broadcast": current["can_broadcast"],
        "is_admin_flag": current["is_admin"],
    }
    if field == "can_notify":
        kwargs["can_notify"] = not current["can_notify"]
    elif field == "can_review":
        kwargs["can_review"] = not current["can_review"]
    elif field == "can_broadcast":
        kwargs["can_broadcast"] = not current["can_broadcast"]
    elif field == "is_admin":
        kwargs["is_admin_flag"] = not current["is_admin"]
    set_user_permissions(callback.from_user.id, target_id, **kwargs)
    profile = get_user_permissions(target_id)
    approved = get_approved_user(target_id) or {}
    profile_view = dict(profile)
    profile_view["is_grant"] = bool(approved.get("is_grant"))
    await callback.message.edit_reply_markup(reply_markup=ikb.get_admin_user_actions_kb(target_id, profile_view))
    await callback.answer("Права обновлены.")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_TOGGLE_NOTIFY_PREFIX))
async def admin_toggle_notify(callback: types.CallbackQuery):
    await _toggle_permission(callback, CallbackData.ADMIN_TOGGLE_NOTIFY_PREFIX, "can_notify")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_TOGGLE_REVIEW_PREFIX))
async def admin_toggle_review(callback: types.CallbackQuery):
    await _toggle_permission(callback, CallbackData.ADMIN_TOGGLE_REVIEW_PREFIX, "can_review")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_TOGGLE_ADMIN_PREFIX))
async def admin_toggle_admin(callback: types.CallbackQuery):
    await _toggle_permission(callback, CallbackData.ADMIN_TOGGLE_ADMIN_PREFIX, "is_admin")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_TOGGLE_BROADCAST_PREFIX))
async def admin_toggle_broadcast(callback: types.CallbackQuery):
    await _toggle_permission(callback, CallbackData.ADMIN_TOGGLE_BROADCAST_PREFIX, "can_broadcast")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_TOGGLE_GRANT_PREFIX))
async def admin_toggle_grant(callback: types.CallbackQuery):
    await callback.answer("Флаг «Грантник» убран из панели выдачи доступов.", show_alert=True)


@router.callback_query(F.data.startswith(CallbackData.ADMIN_ASSIGN_SPECS_PREFIX))
async def admin_assign_specialties(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_ASSIGN_SPECS_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    await callback.message.edit_text(
        "🎯 Выберите уровень для назначения специальностей:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🏛 Университет",
                        callback_data=f"{CallbackData.ADMIN_SPECS_TRACK_PREFIX}{target_id}_uni",
                    ),
                    types.InlineKeyboardButton(
                        text="🏫 Колледж",
                        callback_data=f"{CallbackData.ADMIN_SPECS_TRACK_PREFIX}{target_id}_college",
                    ),
                ],
                [types.InlineKeyboardButton(text="🔙 К пользователю", callback_data=f"{CallbackData.ADMIN_USER_PREFIX}{target_id}")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_ASSIGN_GROUPS_PREFIX))
async def admin_assign_groups(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_ASSIGN_GROUPS_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    await callback.message.edit_text(
        "🧩 Выберите уровень для назначения групп:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🏛 Университет",
                        callback_data=f"{CallbackData.ADMIN_GROUPS_TRACK_PREFIX}{target_id}_uni",
                    ),
                    types.InlineKeyboardButton(
                        text="🏫 Колледж",
                        callback_data=f"{CallbackData.ADMIN_GROUPS_TRACK_PREFIX}{target_id}_college",
                    ),
                ],
                [types.InlineKeyboardButton(text="🔙 К пользователю", callback_data=f"{CallbackData.ADMIN_USER_PREFIX}{target_id}")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUPS_TRACK_PREFIX))
async def admin_groups_track(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_GROUPS_TRACK_PREFIX, "")
    user_id_raw, _, track_raw = payload.partition("_")
    if not user_id_raw.isdigit() or track_raw not in {"uni", "college"}:
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    track = "college" if track_raw == "college" else "uni"
    current = get_user_permissions(target_id)
    allowed_specialties = list(current.get("specialties", []))
    all_groups = list_groups_for_specialties(track=track, specialties=allowed_specialties)
    if not all_groups:
        await callback.answer("Сначала назначьте сотруднику доверенные специальности.", show_alert=True)
        return
    selected_indexes = {idx for idx, value in enumerate(all_groups) if value in set(current.get("groups", []))}
    state_data = await state.get_data()
    selected_map = _get_admin_groups_selected_map(state_data)
    selected_map[str(target_id)] = sorted(selected_indexes)
    track_map = _get_admin_groups_track_map(state_data)
    track_map[str(target_id)] = track
    await state.update_data(**{ADMIN_GROUPS_SELECTED_KEY: selected_map, ADMIN_GROUPS_TRACK_KEY: track_map})
    page_items, page, total_pages = _groups_page_payload(0, all_groups)
    await callback.message.edit_text(
        f"🧩 Выберите группы ({'Колледж' if track == 'college' else 'Университет'}). Можно отметить несколько.",
        reply_markup=ikb.get_admin_groups_kb(
            target_user_id=target_id,
            groups=page_items,
            selected_indexes=selected_indexes,
            page=page,
            total_pages=total_pages,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUPS_PAGE_PREFIX))
async def admin_groups_page(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_GROUPS_PAGE_PREFIX, "")
    user_id_raw, _, page_raw = payload.partition("_")
    if not user_id_raw.isdigit() or not page_raw.isdigit():
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    page = int(page_raw)
    state_data = await state.get_data()
    track = _selected_groups_track_for_user(state_data, target_id)
    current = get_user_permissions(target_id)
    all_groups = list_groups_for_specialties(track=track, specialties=list(current.get("specialties", [])))
    selected_indexes = _selected_groups_for_user(state_data, target_id)
    page_items, safe_page, total_pages = _groups_page_payload(page, all_groups)
    await callback.message.edit_reply_markup(
        reply_markup=ikb.get_admin_groups_kb(
            target_user_id=target_id,
            groups=page_items,
            selected_indexes=selected_indexes,
            page=safe_page,
            total_pages=total_pages,
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUPS_TOGGLE_PREFIX))
async def admin_groups_toggle(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_GROUPS_TOGGLE_PREFIX, "")
    user_id_raw, _, index_raw = payload.partition("_")
    if not user_id_raw.isdigit() or not index_raw.isdigit():
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    toggled_index = int(index_raw)
    state_data = await state.get_data()
    track = _selected_groups_track_for_user(state_data, target_id)
    current = get_user_permissions(target_id)
    all_groups = list_groups_for_specialties(track=track, specialties=list(current.get("specialties", [])))
    if toggled_index < 0 or toggled_index >= len(all_groups):
        await callback.answer("Группа не найдена.", show_alert=True)
        return
    selected_map = _get_admin_groups_selected_map(state_data)
    selected_indexes = _selected_groups_for_user(state_data, target_id)
    if toggled_index in selected_indexes:
        selected_indexes.remove(toggled_index)
    else:
        selected_indexes.add(toggled_index)
    selected_map[str(target_id)] = sorted(selected_indexes)
    await state.update_data(**{ADMIN_GROUPS_SELECTED_KEY: selected_map})
    page = toggled_index // ADMIN_GROUPS_PAGE_SIZE
    page_items, safe_page, total_pages = _groups_page_payload(page, all_groups)
    await callback.message.edit_reply_markup(
        reply_markup=ikb.get_admin_groups_kb(
            target_user_id=target_id,
            groups=page_items,
            selected_indexes=selected_indexes,
            page=safe_page,
            total_pages=total_pages,
        )
    )
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUPS_APPLY_PREFIX))
async def admin_groups_apply(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_GROUPS_APPLY_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    state_data = await state.get_data()
    track = _selected_groups_track_for_user(state_data, target_id)
    current = get_user_permissions(target_id)
    all_groups = list_groups_for_specialties(track=track, specialties=list(current.get("specialties", [])))
    selected_indexes = sorted(_selected_groups_for_user(state_data, target_id))
    selected_groups = [all_groups[idx] for idx in selected_indexes if 0 <= idx < len(all_groups)]
    set_user_permissions(callback.from_user.id, target_id, groups=selected_groups, can_notify=True, can_review=True)
    await callback.message.edit_text(
        f"✅ Группы назначены ({'Колледж' if track == 'college' else 'Университет'}):\n"
        f"{', '.join(selected_groups) if selected_groups else '-'}",
        reply_markup=ikb.get_admin_user_actions_kb(
            target_id,
            {**get_user_permissions(target_id), "is_grant": bool((get_approved_user(target_id) or {}).get("is_grant"))},
        ),
    )
    await callback.answer("Сохранено.")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_GROUPS_RESET_PREFIX))
async def admin_groups_reset(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_GROUPS_RESET_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    state_data = await state.get_data()
    selected_map = _get_admin_groups_selected_map(state_data)
    selected_map[str(target_id)] = []
    await state.update_data(**{ADMIN_GROUPS_SELECTED_KEY: selected_map})
    await callback.answer("Выбор групп сброшен.")
@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_TRACK_PREFIX))
async def admin_specs_track(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_SPECS_TRACK_PREFIX, "")
    user_id_raw, _, track_raw = payload.partition("_")
    if not user_id_raw.isdigit() or track_raw not in {"uni", "college"}:
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    track = "college" if track_raw == "college" else "uni"
    all_specialties = get_all_specialties("ru", track=track)
    current = get_user_permissions(target_id)
    selected_indexes = {idx for idx, value in enumerate(all_specialties) if value in set(current.get("specialties", []))}
    state_data = await state.get_data()
    selected_map = _get_admin_selected_map(state_data)
    selected_map[str(target_id)] = sorted(selected_indexes)
    track_map = _get_admin_track_map(state_data)
    track_map[str(target_id)] = track
    await state.update_data(**{ADMIN_SPECS_SELECTED_KEY: selected_map, ADMIN_SPECS_TRACK_KEY: track_map})
    page_items, page, total_pages = _specialties_page_payload(0, all_specialties)
    await callback.message.edit_text(
        f"🎯 Выберите специальности ({'Колледж' if track == 'college' else 'Университет'}). Можно отметить несколько.",
        reply_markup=ikb.get_admin_specialties_kb(
            target_user_id=target_id,
            specialties=page_items,
            selected_indexes=selected_indexes,
            page=page,
            total_pages=total_pages,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_PAGE_PREFIX))
async def admin_specs_page(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_SPECS_PAGE_PREFIX, "")
    user_id_raw, _, page_raw = payload.partition("_")
    if not user_id_raw.isdigit() or not page_raw.isdigit():
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    page = int(page_raw)
    state_data = await state.get_data()
    track = _selected_track_for_user(state_data, target_id)
    all_specialties = get_all_specialties("ru", track=track)
    selected_indexes = _selected_for_user(state_data, target_id)
    page_items, safe_page, total_pages = _specialties_page_payload(page, all_specialties)
    await callback.message.edit_reply_markup(
        reply_markup=ikb.get_admin_specialties_kb(
            target_user_id=target_id,
            specialties=page_items,
            selected_indexes=selected_indexes,
            page=safe_page,
            total_pages=total_pages,
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_TOGGLE_PREFIX))
async def admin_specs_toggle(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.ADMIN_SPECS_TOGGLE_PREFIX, "")
    user_id_raw, _, index_raw = payload.partition("_")
    if not user_id_raw.isdigit() or not index_raw.isdigit():
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    target_id = int(user_id_raw)
    toggled_index = int(index_raw)
    state_data = await state.get_data()
    track = _selected_track_for_user(state_data, target_id)
    all_specialties = get_all_specialties("ru", track=track)
    if toggled_index < 0 or toggled_index >= len(all_specialties):
        await callback.answer("Специальность не найдена.", show_alert=True)
        return
    selected_map = _get_admin_selected_map(state_data)
    selected_indexes = _selected_for_user(state_data, target_id)
    if toggled_index in selected_indexes:
        selected_indexes.remove(toggled_index)
    else:
        selected_indexes.add(toggled_index)
    selected_map[str(target_id)] = sorted(selected_indexes)
    await state.update_data(**{ADMIN_SPECS_SELECTED_KEY: selected_map})
    page = toggled_index // ADMIN_SPECS_PAGE_SIZE
    page_items, safe_page, total_pages = _specialties_page_payload(page, all_specialties)
    await callback.message.edit_reply_markup(
        reply_markup=ikb.get_admin_specialties_kb(
            target_user_id=target_id,
            specialties=page_items,
            selected_indexes=selected_indexes,
            page=safe_page,
            total_pages=total_pages,
        )
    )
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_CONFIRM_PREFIX))
async def admin_specs_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_SPECS_CONFIRM_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    state_data = await state.get_data()
    track = _selected_track_for_user(state_data, target_id)
    all_specialties = get_all_specialties("ru", track=track)
    selected_indexes = sorted(_selected_for_user(state_data, target_id))
    selected_specialties = [all_specialties[idx] for idx in selected_indexes if 0 <= idx < len(all_specialties)]
    approved = get_approved_user(target_id) or {}
    info_lines = [
        "Подтвердите назначение ответственного:",
        f"👤 Пользователь: {approved.get('fio', '-')}",
        f"🆔 Telegram ID: {target_id}",
        f"🔗 Username: @{approved.get('tg_username')}" if approved.get("tg_username") else "🔗 Username: -",
        f"🎓 Уровень: {'Колледж' if track == 'college' else 'Университет'}",
        f"🎓 Специальности ({len(selected_specialties)}):",
        ", ".join(selected_specialties) if selected_specialties else "-",
    ]
    await callback.message.edit_text("\n".join(info_lines), reply_markup=ikb.get_admin_specs_confirm_kb(target_id))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_APPLY_PREFIX))
async def admin_specs_apply(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_SPECS_APPLY_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    state_data = await state.get_data()
    track = _selected_track_for_user(state_data, target_id)
    all_specialties = get_all_specialties("ru", track=track)
    selected_indexes = sorted(_selected_for_user(state_data, target_id))
    selected_specialties = [all_specialties[idx] for idx in selected_indexes if 0 <= idx < len(all_specialties)]
    set_user_permissions(
        callback.from_user.id,
        target_id,
        can_notify=True,
        can_review=True,
        specialties=selected_specialties,
    )
    approved = get_approved_user(target_id) or {}
    info_lines = [
        "✅ Назначение подтверждено.",
        f"👤 Пользователь: {approved.get('fio', '-')}",
        f"🆔 Telegram ID: {target_id}",
        f"🔗 Username: @{approved.get('tg_username')}" if approved.get("tg_username") else "🔗 Username: -",
        f"🎓 Уровень: {'Колледж' if track == 'college' else 'Университет'}",
        f"🎓 Специальности ({len(selected_specialties)}):",
        ", ".join(selected_specialties) if selected_specialties else "-",
    ]
    await callback.message.edit_text(
        "\n".join(info_lines),
        reply_markup=ikb.get_admin_user_actions_kb(
            target_id,
            {**get_user_permissions(target_id), "is_grant": bool((get_approved_user(target_id) or {}).get("is_grant"))},
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.ADMIN_SPECS_RESET_PREFIX))
async def admin_specs_reset(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id_raw = callback.data.replace(CallbackData.ADMIN_SPECS_RESET_PREFIX, "")
    if not user_id_raw.isdigit():
        await callback.answer("Некорректный ID", show_alert=True)
        return
    target_id = int(user_id_raw)
    state_data = await state.get_data()
    selected_map = _get_admin_selected_map(state_data)
    selected_map[str(target_id)] = []
    await state.update_data(**{ADMIN_SPECS_SELECTED_KEY: selected_map})
    await callback.answer("Выбор сброшен.")
    await callback.message.edit_text(
        "Выбор специальностей сброшен. Вы можете начать заново.",
        reply_markup=ikb.get_admin_user_actions_kb(
            target_id,
            {**get_user_permissions(target_id), "is_grant": bool((get_approved_user(target_id) or {}).get("is_grant"))},
        ),
    )


@router.message(Command("set_groups"))
async def admin_set_groups(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /set_groups <user_id> <группа1,группа2|*>")
        return
    target_id = int(parts[1])
    groups = [item.strip() for item in parts[2].split(",") if item.strip()]
    if not groups:
        await message.answer("Нужно указать хотя бы одну группу или *")
        return
    set_user_permissions(message.from_user.id, target_id, groups=groups)
    await message.answer(f"✅ Группы для {target_id} обновлены: {', '.join(groups)}")


@router.message(Command("set_faculties"))
async def admin_set_faculties(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /set_faculties <user_id> <кафедра1,кафедра2|*>")
        return
    target_id = int(parts[1])
    faculties = [item.strip() for item in parts[2].split(",") if item.strip()]
    if not faculties:
        await message.answer("Нужно указать хотя бы одну кафедру или *")
        return
    known = set(get_all_faculties("ru"))
    if "*" not in faculties:
        unknown = [item for item in faculties if item not in known]
        if unknown:
            await message.answer(f"Неизвестные кафедры: {', '.join(unknown)}")
            return
    set_user_permissions(message.from_user.id, target_id, faculties=faculties)
    await message.answer(f"✅ Кафедры для {target_id} обновлены: {', '.join(faculties)}")


@router.message(Command("create_group"))
async def admin_create_group(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    payload = (message.text or "").replace("/create_group", "", 1).strip()
    # Формат: /create_group track|faculty|specialty|course|group
    chunks = [item.strip() for item in payload.split("|")]
    if len(chunks) != 5:
        await message.answer("Формат: /create_group <uni|college>|<кафедра>|<специальность>|<курс>|<группа>")
        return
    track, faculty, specialty, course, group_name = chunks
    if track not in {"uni", "college"}:
        await message.answer("Track должен быть uni или college.")
        return
    ok = add_group(
        track=track,
        faculty=faculty,
        specialty=specialty,
        course=course,
        group_name=group_name,
        created_by=message.from_user.id,
    )
    if not ok:
        await message.answer("Не удалось добавить группу (возможно, уже существует или неполные данные).")
        return
    await state.update_data(last_created_group=group_name)
    await message.answer(f"✅ Группа добавлена: {group_name} ({specialty}, курс {course}, {track}).")