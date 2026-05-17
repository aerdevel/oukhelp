"""Личный кабинет сотрудника: рабочее место (заявки, уведомления, расписание, мероприятия)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.resources.text_file.catalog import get_specialties_by_department
from handlers import registration as reg_handlers
from keyboards.inline import review as review_kb
from keyboards.inline import workplace as wp_kb
from services.access_control import can_review, get_user_permissions, is_admin
from services.staff_eligibility import can_use_workplace
from services.broadcast_scope import deliver_text_broadcast
from utils.text_links import split_body_and_link
from services.excel_registry import upsert_registration_account_record
from services.registration_store import get_approved_user, update_approved_profile
from services.staff_schedule import (
    get_schedule_photo,
    list_schedule_photos_for_groups,
    upsert_schedule_photo,
    visible_groups_for_staff,
)
from services.study_groups import list_groups_detailed
from utils.safe_telegram import safe_edit_reply_markup
from services.staff_workplace import resolve_workplace_recipients
from states.states import StaffCabinetFlow, StaffWorkplaceFlow
from utils.i18n import tr

router = Router()

_WP_SCHED_NAV_KEY = "wp_sched_nav"

_ROLE_MAP = {
    "role_stud": "Студент",
    "role_grad": "Выпускник",
}


async def _staff_access(user_id: int) -> bool:
    return await can_use_workplace(user_id)


@router.callback_query(F.data == CallbackData.STUDENT_MY_SCHEDULE)
async def student_my_schedule(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    profile = await get_approved_user(callback.from_user.id)
    if not profile:
        await callback.answer(tr(lang, "Кабинет недоступен.", "Кабинет қолжетімсіз."), show_alert=True)
        return
    group = str(profile.get("group", "")).strip()
    if not group or group == "-":
        await callback.answer(tr(lang, "Группа не указана.", "Топ көрсетілмеген."), show_alert=True)
        return
    track = str(profile.get("admission_track", "uni"))
    track_key = track if track in {"uni", "college"} else "uni"
    photo = await get_schedule_photo(group, track=track_key)
    menu_cb = CallbackData.LEVEL_COLL if track == "college" else CallbackData.LEVEL_UNI
    if not photo:
        await callback.answer(
            tr(lang, "Расписание ещё не загружено.", "Кесте әлі жүктелмеген."),
            show_alert=True,
        )
        return
    caption = tr(lang, f"📅 Расписание — группа {group}", f"📅 Кесте — {group} тобы")
    file_id = photo["photo_file_id"]
    if photo.get("photo_kind") == "document":
        await callback.message.answer_document(file_id, caption=caption, reply_markup=wp_kb.get_student_schedule_back_kb(lang, menu_cb))
    else:
        await callback.message.answer_photo(file_id, caption=caption, reply_markup=wp_kb.get_student_schedule_back_kb(lang, menu_cb))
    await callback.answer()


@router.callback_query(F.data == CallbackData.CABINET_WORKPLACE)
async def cabinet_workplace_hub(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.set_state(None)
    text = tr(
        lang,
        "🧰 Рабочее место\n\n"
        "• Заявки — модерация регистраций в вашей зоне\n"
        "• Уведомления — рассылка подопечным (можно без фильтра по специальности)\n"
        "• Расписание — фото на неделю по группам, рассылка студентам\n"
        "• Мероприятие — сообщение со ссылкой-кнопкой (LINK: https://...)\n"
        "• Смена группы студента",
        "🧰 Жұмыс орны\n\n"
        "• Өтінімдер — сіздің аймағыңыздағы тіркеулер\n"
        "• Хабарламалар — тәлімгерлеріңізге\n"
        "• Кесте — қарау, қосу, топтарға жіберу\n"
        "• Іс-шара — сілтемелі хабарлама\n"
        "• Топты өзгерту",
    )
    from utils.safe_telegram import edit_or_send_text

    await edit_or_send_text(callback.message, text, reply_markup=wp_kb.get_workplace_hub_kb(lang))
    await callback.answer()


@router.callback_query(F.data == CallbackData.STAFF_WP_REVIEW)
async def staff_wp_review(callback: types.CallbackQuery, state: FSMContext):
    if not await _staff_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.update_data(review_back_callback=CallbackData.CABINET_WORKPLACE)
    await reg_handlers.review_registrations(callback, state)


# --- Уведомления ---


@router.callback_query(F.data == CallbackData.STAFF_WP_NOTIFY)
async def staff_wp_notify_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.update_data(wp_mode="notify", wp_filter={})
    await callback.message.edit_text(
        tr(lang, "Настройте фильтр аудитории (можно пропустить специальность).", "Аудитория сүзгісін баптаңыз."),
        reply_markup=wp_kb.get_workplace_notify_filters_kb(lang, {}),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wpfil_"))
async def staff_wp_notify_filter(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if data.get("wp_mode") != "notify":
        return
    raw = callback.data.replace("wpfil_", "")
    nf: dict[str, Any] = dict(data.get("wp_filter") or {})
    if raw == "track_uni":
        nf["track"] = "uni"
    elif raw == "track_college":
        nf["track"] = "college"
    elif raw.startswith("role_"):
        role = _ROLE_MAP.get(raw)
        if role:
            nf["role"] = role
    elif raw == "skip_spec":
        nf.pop("specialty", None)
        nf["skip_specialty"] = True
    elif raw == "done":
        await state.update_data(wp_filter=nf)
        await state.set_state(StaffWorkplaceFlow.notify_waiting_text)
        n = len(
            await resolve_workplace_recipients(
                callback.from_user.id,
                track=nf.get("track"),
                role=nf.get("role"),
                group=nf.get("group"),
                specialty=None if nf.get("skip_specialty") else nf.get("specialty"),
            )
        )
        await callback.message.edit_text(
            tr(
                lang,
                f"Пришлите текст уведомления (оценочно получателей: {n}).\n"
                "Ссылка-кнопка: строка LINK: https://... в конце.",
                f"Хабарлама мәтінін жіберіңіз (шамамен {n} адам).\n"
                "Сілтеме: LINK: https://...",
            )
        )
        await callback.answer()
        return
    await state.update_data(wp_filter=nf)
    await safe_edit_reply_markup(
        callback.message,
        reply_markup=wp_kb.get_workplace_notify_filters_kb(lang, nf),
    )
    await callback.answer()


@router.message(StaffWorkplaceFlow.notify_waiting_text, F.text)
async def staff_wp_notify_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(message.from_user.id):
        await state.set_state(None)
        return
    body, link = split_body_and_link(message.text or "")
    if not body.strip():
        await message.answer(tr(lang, "Пустой текст.", "Бос мәтін."))
        return
    nf = dict(data.get("wp_filter") or {})
    targets = await resolve_workplace_recipients(
        message.from_user.id,
        track=nf.get("track"),
        role=nf.get("role"),
        group=nf.get("group"),
        specialty=None if nf.get("skip_specialty") else nf.get("specialty"),
    )
    if not targets:
        await message.answer(tr(lang, "Нет получателей.", "Алушылар жоқ."))
        await state.set_state(None)
        return
    label = tr(lang, "Открыть", "Ашу")
    ok, fail = await deliver_text_broadcast(message.bot, targets, body, link_url=link, link_button_text=label)
    await message.answer(tr(lang, f"Доставлено: {ok}, ошибок: {fail}.", f"Жеткізілді: {ok}, қате: {fail}."))
    await state.set_state(None)


# --- Мероприятие ---


@router.callback_query(F.data == CallbackData.STAFF_WP_EVENT)
async def staff_wp_event_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.update_data(wp_mode="event", wp_filter={})
    await state.set_state(StaffWorkplaceFlow.event_waiting_text)
    await callback.message.edit_text(
        tr(
            lang,
            "Текст мероприятия одним сообщением.\n"
            "Добавьте ссылку (место или сайт) строкой:\nLINK: https://...\n\n"
            "Без ссылки — просто не добавляйте строку LINK.",
            "Іс-шара мәтіні.\n"
            "Сілтеме: LINK: https://...\n"
            "Сілтемесіз — LINK жолын қоспаңыз.",
        )
    )
    await callback.answer()


@router.message(StaffWorkplaceFlow.event_waiting_text, F.text)
async def staff_wp_event_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(message.from_user.id):
        await state.set_state(None)
        return
    body, link = split_body_and_link(message.text or "")
    if not body.strip():
        await message.answer(tr(lang, "Пустой текст.", "Бос мәтін."))
        return
    targets = await resolve_workplace_recipients(message.from_user.id)
    if not targets:
        await message.answer(tr(lang, "Нет получателей в вашей зоне.", "Аймағыңызда алушылар жоқ."))
        await state.set_state(None)
        return
    ok, fail = await deliver_text_broadcast(
        message.bot,
        targets,
        body,
        link_url=link,
        link_button_text=tr(lang, "Подробнее", "Толығырақ"),
    )
    await message.answer(tr(lang, f"Мероприятие отправлено: {ok} ок, {fail} ошибок.", f"Жіберілді: {ok}, қате: {fail}."))
    await state.set_state(None)


# --- Расписание ---


@router.callback_query(F.data == CallbackData.STAFF_WP_SCHEDULE)
async def staff_wp_schedule_menu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    from utils.safe_telegram import edit_or_send_text

    await state.set_state(None)
    await edit_or_send_text(
        callback.message,
        tr(lang, "📅 Расписание (фото на неделю по группам)", "📅 Кесте (апталық фото)"),
        reply_markup=wp_kb.get_workplace_schedule_kb(lang),
    )
    await callback.answer()


def _sched_nav(data: dict) -> dict:
    raw = data.get(_WP_SCHED_NAV_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


@router.callback_query(F.data == CallbackData.STAFF_WP_SCHEDULE_VIEW)
async def staff_wp_schedule_view_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not await _staff_access(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    profile = await get_approved_user(callback.from_user.id) or {}
    track = str(profile.get("admission_track", "uni"))
    track_key = track if track in {"uni", "college"} else "uni"
    departments = get_specialties_by_department(lang, track_key)
    builder = InlineKeyboardBuilder()
    for idx, faculty in enumerate(list(departments.keys())[:30]):
        builder.row(
            types.InlineKeyboardButton(
                text=faculty,
                callback_data=f"{CallbackData.STAFF_SCHED_FAC_PREFIX}{idx}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text=tr(lang, "🔙 Назад", "🔙 Артқа"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE,
        )
    )
    await state.update_data(**{_WP_SCHED_NAV_KEY: {"track": track_key}})
    await callback.message.edit_text(
        tr(lang, "Кафедра / бірлестік:", "Кафедра / бірлестік:"),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.STAFF_SCHED_FAC_PREFIX))
async def staff_wp_schedule_pick_faculty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    nav = _sched_nav(data)
    track = nav.get("track", "uni")
    departments = get_specialties_by_department(lang, track)
    faculties = list(departments.keys())
    raw = callback.data.replace(CallbackData.STAFF_SCHED_FAC_PREFIX, "")
    if not raw.isdigit() or int(raw) >= len(faculties):
        await callback.answer()
        return
    fac_idx = int(raw)
    faculty = faculties[fac_idx]
    specs = departments[faculty]
    builder = InlineKeyboardBuilder()
    for idx, spec in enumerate(specs[:30]):
        builder.row(
            types.InlineKeyboardButton(
                text=spec,
                callback_data=f"{CallbackData.STAFF_SCHED_SPEC_PREFIX}{idx}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text=tr(lang, "🔙 Кафедры", "🔙 Кафедралар"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE_VIEW,
        )
    )
    await state.update_data(**{_WP_SCHED_NAV_KEY: {**nav, "faculty": faculty, "faculty_idx": fac_idx}})
    await callback.message.edit_text(
        tr(lang, "Специальность:", "Мамандық:"),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.STAFF_SCHED_SPEC_PREFIX))
async def staff_wp_schedule_pick_specialty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    nav = _sched_nav(data)
    track = nav.get("track", "uni")
    faculty = nav.get("faculty", "")
    specs = get_specialties_by_department(lang, track).get(faculty, [])
    raw = callback.data.replace(CallbackData.STAFF_SCHED_SPEC_PREFIX, "")
    if not raw.isdigit() or int(raw) >= len(specs):
        await callback.answer()
        return
    spec_idx = int(raw)
    specialty = specs[spec_idx]
    builder = InlineKeyboardBuilder()
    for course in ["1", "2", "3", "4", "Graduate"]:
        label = f"{course} курс" if course != "Graduate" else tr(lang, "Выпускник", "Түлек")
        builder.row(
            types.InlineKeyboardButton(
                text=label,
                callback_data=f"{CallbackData.STAFF_SCHED_COURSE_PREFIX}{course}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text=tr(lang, "🔙 Специальности", "🔙 Мамандықтар"),
            callback_data=f"{CallbackData.STAFF_SCHED_FAC_PREFIX}{int(nav.get('faculty_idx', 0))}",
        )
    )
    await state.update_data(**{_WP_SCHED_NAV_KEY: {**nav, "specialty": specialty, "spec_idx": spec_idx}})
    await callback.message.edit_text(tr(lang, "Курс:", "Курс:"), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.STAFF_SCHED_COURSE_PREFIX))
async def staff_wp_schedule_pick_course(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    nav = _sched_nav(data)
    course = callback.data.replace(CallbackData.STAFF_SCHED_COURSE_PREFIX, "")
    track = nav.get("track", "uni")
    faculty = nav.get("faculty", "")
    specialty = nav.get("specialty", "")
    allowed = set(await visible_groups_for_staff(callback.from_user.id))
    rows = await list_groups_detailed(track=track, faculty=faculty, specialty=specialty, course=course)
    rows = [row for row in rows if row["group_name"] in allowed]
    if not rows:
        await callback.answer(
            tr(lang, "Нет доступных групп в этой специальности.", "Бұл мамандықта топтар жоқ."),
            show_alert=True,
        )
        return
    choices = [row["group_name"] for row in rows[:25]]
    builder = InlineKeyboardBuilder()
    for idx, name in enumerate(choices):
        builder.row(
            types.InlineKeyboardButton(
                text=name,
                callback_data=f"{CallbackData.STAFF_SCHED_GRP_PREFIX}{idx}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text=tr(lang, "🔙 Курс", "🔙 Курс"),
            callback_data=f"{CallbackData.STAFF_SCHED_SPEC_PREFIX}{int(nav.get('spec_idx', 0))}",
        )
    )
    await state.update_data(**{_WP_SCHED_NAV_KEY: {**nav, "course": course, "group_choices": choices}})
    await callback.message.edit_text(
        tr(lang, "Группа:", "Топ:"),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.STAFF_SCHED_GRP_PREFIX))
async def staff_wp_schedule_show_group(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    nav = _sched_nav(data)
    track = nav.get("track", "uni")
    raw = callback.data.replace(CallbackData.STAFF_SCHED_GRP_PREFIX, "")
    choices = list(nav.get("group_choices") or [])
    if not raw.isdigit() or int(raw) >= len(choices):
        await callback.answer()
        return
    group_name = choices[int(raw)]
    allowed = set(await visible_groups_for_staff(callback.from_user.id))
    if group_name not in allowed:
        await callback.answer(tr(lang, "Нет доступа к группе.", "Топқа қолжетімділік жоқ."), show_alert=True)
        return
    photo = await get_schedule_photo(group_name, track=track)
    if not photo:
        await callback.answer(
            tr(lang, "Расписание для этой группы ещё не загружено.", "Кесте әлі жүктелмеген."),
            show_alert=True,
        )
        return
    caption = tr(lang, f"📅 {group_name}", f"📅 {group_name}")
    fid = photo["photo_file_id"]
    if photo.get("photo_kind") == "document":
        await callback.message.answer_document(fid, caption=caption)
    else:
        await callback.message.answer_photo(fid, caption=caption)
    await callback.answer()


@router.callback_query(F.data == CallbackData.STAFF_WP_SCHEDULE_UPLOAD)
async def staff_wp_schedule_upload_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    groups = await visible_groups_for_staff(callback.from_user.id)
    if not groups:
        await callback.answer(tr(lang, "Нет доступных групп.", "Топтар жоқ."), show_alert=True)
        return
    await state.update_data(wp_groups=groups, wp_sched={})
    b = InlineKeyboardBuilder()
    for idx, name in enumerate(groups[:25]):
        b.row(types.InlineKeyboardButton(text=name, callback_data=f"{CallbackData.STAFF_WP_GROUP_PREFIX}{idx}"))
    b.row(
        types.InlineKeyboardButton(
            text=tr(lang, "🔙 Назад", "🔙 Артқа"),
            callback_data=CallbackData.STAFF_WP_SCHEDULE,
        )
    )
    b.row(types.InlineKeyboardButton(text=tr(lang, "Отмена", "Болдырмау"), callback_data=CallbackData.STAFF_WP_ABORT))
    await callback.message.edit_text(
        tr(lang, "Выберите группу для загрузки фото расписания:", "Кесте фотосы үшін топты таңдаңыз:"),
        reply_markup=b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.STAFF_WP_GROUP_PREFIX))
async def staff_wp_schedule_pick_group(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    idx_raw = callback.data.replace(CallbackData.STAFF_WP_GROUP_PREFIX, "")
    if not idx_raw.isdigit():
        await callback.answer()
        return
    groups = data.get("wp_groups") or []
    idx = int(idx_raw)
    if idx < 0 or idx >= len(groups):
        await callback.answer()
        return
    sched = dict(data.get("wp_sched") or {})
    sched["group_name"] = groups[idx]
    await state.update_data(wp_sched=sched)
    await state.set_state(StaffWorkplaceFlow.schedule_waiting_photo)
    await callback.message.edit_text(
        tr(
            lang,
            f"Отправьте одним сообщением фото расписания на неделю для группы {groups[idx]}.",
            f"{groups[idx]} тобына апталық кесте фотосын жіберіңіз.",
        )
    )
    await callback.answer()


@router.message(StaffWorkplaceFlow.schedule_waiting_photo, F.photo | F.document)
async def staff_wp_schedule_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    sched = dict(data.get("wp_sched") or {})
    group_name = str(sched.get("group_name", "")).strip()
    if not group_name:
        await state.set_state(None)
        return
    if message.photo:
        file_id = message.photo[-1].file_id
        kind = "photo"
    elif message.document:
        file_id = message.document.file_id
        kind = "document"
    else:
        await message.answer(tr(lang, "Нужно фото или файл-изображение.", "Фото керек."))
        return
    profile = await get_approved_user(message.from_user.id) or {}
    track = str(profile.get("admission_track", "uni"))
    await upsert_schedule_photo(
        created_by=message.from_user.id,
        admission_track=track,
        group_name=group_name,
        photo_file_id=file_id,
        photo_kind=kind,
    )
    await state.set_state(None)
    await message.answer(
        tr(lang, f"✅ Расписание для {group_name} сохранено.", f"✅ {group_name} кестесі сақталды."),
        reply_markup=wp_kb.get_workplace_schedule_kb(lang),
    )


@router.callback_query(F.data == CallbackData.STAFF_WP_SCHEDULE_SEND)
async def staff_wp_schedule_broadcast(callback: types.CallbackQuery, state: FSMContext):
    from services.registration_store import get_approved_all

    data = await state.get_data()
    lang = data.get("locale", "ru")
    profile = await get_approved_user(callback.from_user.id) or {}
    track = str(profile.get("admission_track", "uni"))
    track_key = track if track in {"uni", "college"} else "uni"
    groups = await visible_groups_for_staff(callback.from_user.id)
    photos = {p["group_name"]: p for p in await list_schedule_photos_for_groups(groups, track=track_key)}
    if not photos:
        await callback.answer(tr(lang, "Сначала загрузите фото.", "Алдымен фото жүктеңіз."), show_alert=True)
        return
    rows = await get_approved_all()
    by_group: dict[str, list[int]] = {}
    for row in rows:
        gid = int(row.get("tg_user_id") or 0)
        grp = str(row.get("group", "")).strip()
        if not gid or not grp or grp == "-":
            continue
        if await can_review(callback.from_user.id, grp, row.get("specialty")):
            by_group.setdefault(grp, []).append(gid)
    ok_total = 0
    for grp in groups:
        photo = photos.get(grp)
        ids = by_group.get(grp) or []
        if not photo or not ids:
            continue
        caption = tr(lang, f"📅 Расписание — {grp}", f"📅 Кесте — {grp}")
        fid = photo["photo_file_id"]
        for uid in ids:
            try:
                if photo.get("photo_kind") == "document":
                    await callback.bot.send_document(uid, fid, caption=caption)
                else:
                    await callback.bot.send_photo(uid, fid, caption=caption)
                ok_total += 1
            except Exception:
                pass
    await callback.answer(tr(lang, f"Отправлено: {ok_total}", f"Жіберілді: {ok_total}"), show_alert=True)


@router.callback_query(F.data == CallbackData.STAFF_WP_ABORT)
async def staff_wp_abort(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await cabinet_workplace_hub(callback, state)


# --- Смена группы (как было) ---


@router.callback_query(F.data == CallbackData.STAFF_REASSIGN_START)
async def staff_reassign_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    perms = await get_user_permissions(callback.from_user.id)
    if not (await is_admin(callback.from_user.id) or perms.get("can_review")):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.set_state(StaffCabinetFlow.reassign_enter_user_id)
    await callback.message.answer(
        tr(
            lang,
            "Введите Telegram user id студента (цифры).",
            "Студенттің Telegram user id енгізіңіз.",
        )
    )
    await callback.answer()


@router.message(StaffCabinetFlow.reassign_enter_user_id, F.text)
async def staff_reassign_got_id(message: types.Message, state: FSMContext):
    from utils.validators import MIN_GROUP_NAME_LEN, sanitize_text, validate_min_plaintext

    data = await state.get_data()
    lang = data.get("locale", "ru")
    actor_id = message.from_user.id
    perms = await get_user_permissions(actor_id)
    if not (await is_admin(actor_id) or perms.get("can_review")):
        await state.set_state(None)
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(tr(lang, "Нужны только цифры user id.", "Тек сандар керек."))
        return
    uid = int(raw)
    target = await get_approved_user(uid)
    if not target:
        await message.answer(tr(lang, "Пользователь не найден.", "Табылмады."))
        return
    if not await can_review(actor_id, str(target.get("group", "-")), target.get("specialty")):
        await message.answer(tr(lang, "Нет доступа по ACL.", "ACL жоқ."))
        return
    await state.update_data(reassign_target_id=uid)
    await state.set_state(StaffCabinetFlow.reassign_enter_group)
    await message.answer(
        tr(
            lang,
            f"Текущая группа: {target.get('group', '-')}. Введите новую:",
            f"Ағымдағы топ: {target.get('group', '-')}. Жаңасын енгізіңіз:",
        )
    )


@router.message(StaffCabinetFlow.reassign_enter_group, F.text)
async def staff_reassign_got_group(message: types.Message, state: FSMContext):
    from utils.validators import MIN_GROUP_NAME_LEN, sanitize_text, validate_min_plaintext

    data = await state.get_data()
    lang = data.get("locale", "ru")
    actor_id = message.from_user.id
    perms = await get_user_permissions(actor_id)
    if not (await is_admin(actor_id) or perms.get("can_review")):
        await state.set_state(None)
        return
    uid = data.get("reassign_target_id")
    if not isinstance(uid, int):
        await state.set_state(None)
        return
    group = sanitize_text(message.text or "")
    if not validate_min_plaintext(group, min_len=MIN_GROUP_NAME_LEN):
        await message.answer(tr(lang, f"Минимум {MIN_GROUP_NAME_LEN} символа.", f"Кемінде {MIN_GROUP_NAME_LEN} таңба."))
        return
    target = await get_approved_user(uid)
    if not target or not await can_review(actor_id, str(target.get("group", "-")), target.get("specialty")):
        await state.set_state(None)
        return
    updated = await update_approved_profile(uid, group=group)
    if not updated:
        await message.answer(tr(lang, "Ошибка обновления.", "Қате."))
        return
    try:
        upsert_registration_account_record(updated)
    except Exception as err:
        logging.warning("excel sync reassign: %s", err)
    await state.set_state(None)
    await message.answer(tr(lang, f"Группа: {group}", f"Топ: {group}"))
    try:
        await message.bot.send_message(uid, tr(lang, f"Группа обновлена: {group}", f"Топ жаңартылды: {group}"))
    except Exception:
        pass
