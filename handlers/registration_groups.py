"""Регистрация: мульти-группы и несколько кафедр/специальностей для преподавателя."""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from core.callbacks import CallbackData
from handlers.registration import _send_preview, _track_from_state
from keyboards.inline import menu as ikb
from services.study_groups import add_group, list_all_groups, list_groups_for_specialties
from services.teaching_assignments import assignments_summary, flatten_for_profile, normalize_assignments
from states.states import Form
from utils.i18n import tr
from utils.registration_flow import is_worker_role
from utils.safe_telegram import safe_edit_reply_markup
from utils.validators import MIN_GROUP_NAME_LEN, sanitize_text, validate_min_plaintext

router = Router()


async def _merged_group_catalog(data: dict, *, all_track: bool = False) -> list[str]:
    track = _track_from_state(data)
    specialty = str(data.get("specialty", "")).strip()
    if all_track:
        return await list_all_groups(track=track)
    by_spec = await list_groups_for_specialties(track=track, specialties=[specialty]) if specialty else []
    return list(dict.fromkeys(by_spec))


async def _show_teaching_groups_picker(target: types.CallbackQuery | types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("locale", "ru")
    groups = await _merged_group_catalog(data)
    selected = set(data.get("selected_teaching_groups") or [])
    if not groups:
        text = tr(
            lang,
            "Групп в справочнике нет. Создайте новую или отметьте «Вся специальность».",
            "Топтар жоқ. Жаңасын құрыңыз немесе «Бүкіл мамандық» таңдаңыз.",
        )
    else:
        text = tr(
            lang,
            "Выберите группы или «Вся специальность», если отвечаете за всю спец. целиком:",
            "Топтарды немесе «Бүкіл мамандық» таңдаңыз:",
        )
    await state.update_data(
        available_groups=groups,
        selected_teaching_groups=list(selected),
        current_assignment_specialty_wide=False,
    )
    await state.set_state(Form.teaching_groups)
    markup = ikb.get_teaching_groups_kb(lang, groups, selected)
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def enter_teaching_groups_flow(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if is_worker_role(data.get("role")):
        from handlers.registration import _send_preview

        await _send_preview(callback, state)
        return
    role = str(data.get("role", ""))
    if role == "Преподаватель" and not data.get("teaching_assignments"):
        await state.update_data(teaching_assignments=[])
    await state.update_data(course="-", selected_teaching_groups=[])
    await _show_teaching_groups_picker(callback, state)
    await callback.answer()


@router.callback_query(Form.teaching_groups, F.data.startswith(CallbackData.REG_GRP_TOGGLE_PREFIX))
async def reg_grp_toggle(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    idx_raw = callback.data.replace(CallbackData.REG_GRP_TOGGLE_PREFIX, "")
    groups = list(data.get("available_groups") or [])
    if not idx_raw.isdigit():
        await callback.answer()
        return
    idx = int(idx_raw)
    if idx < 0 or idx >= len(groups):
        await callback.answer()
        return
    selected = set(data.get("selected_teaching_groups") or [])
    name = groups[idx]
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    await state.update_data(selected_teaching_groups=sorted(selected), current_assignment_specialty_wide=False)
    await safe_edit_reply_markup(
        callback.message,
        reply_markup=ikb.get_teaching_groups_kb(lang, groups, selected),
    )
    await callback.answer()


@router.callback_query(Form.teaching_groups, F.data.startswith("rgpage_"))
async def reg_grp_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    page_raw = callback.data.replace("rgpage_", "")
    if not page_raw.isdigit():
        await callback.answer()
        return
    groups = list(data.get("available_groups") or [])
    selected = set(data.get("selected_teaching_groups") or [])
    await safe_edit_reply_markup(
        callback.message,
        reply_markup=ikb.get_teaching_groups_kb(lang, groups, selected, page=int(page_raw)),
    )
    await callback.answer()


@router.callback_query(Form.teaching_groups, F.data == CallbackData.REG_GRP_SPEC_WIDE)
async def reg_grp_spec_wide(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.update_data(selected_teaching_groups=[], current_assignment_specialty_wide=True)
    groups = list(data.get("available_groups") or [])
    await safe_edit_reply_markup(
        callback.message,
        reply_markup=ikb.get_teaching_groups_kb(lang, groups, set()),
    )
    await callback.answer(
        tr(lang, "Ответственность за всю специальность.", "Бүкіл мамандық бойынша жауапкершілік."),
        show_alert=True,
    )


@router.callback_query(Form.teaching_groups, F.data == CallbackData.REG_GRP_ALL_TRACK)
async def reg_grp_all_track(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    groups = await _merged_group_catalog(data, all_track=True)
    selected = set(data.get("selected_teaching_groups") or [])
    await state.update_data(available_groups=groups)
    await callback.message.edit_text(
        tr(lang, "Группы всего трека:", "Тректің барлық топтары:"),
        reply_markup=ikb.get_teaching_groups_kb(lang, groups, selected),
    )
    await callback.answer()


@router.callback_query(Form.teaching_groups, F.data == CallbackData.REG_GRP_CREATE)
async def reg_grp_create_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.set_state(Form.teaching_group_create)
    await callback.message.edit_text(
        tr(lang, "Введите название новой группы:", "Жаңа топ атауын енгізіңіз:")
    )
    await callback.answer()


@router.message(Form.teaching_group_create, F.text)
async def reg_grp_create_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    name = sanitize_text(message.text or "")
    if not validate_min_plaintext(name, min_len=MIN_GROUP_NAME_LEN):
        await message.answer(tr(lang, f"Минимум {MIN_GROUP_NAME_LEN} символа.", f"Кемінде {MIN_GROUP_NAME_LEN} таңба."))
        return
    faculty = str(data.get("faculty", "-"))
    specialty = str(data.get("specialty", "-"))
    course = str(data.get("course", "-")) if str(data.get("course", "-")) not in {"", "-"} else "-"
    ok = await add_group(
        track=track,
        faculty=faculty,
        specialty=specialty,
        course=course,
        group_name=name,
        created_by=message.from_user.id,
    )
    if not ok:
        await message.answer(tr(lang, "Не удалось создать (возможно, уже есть).", "Құру сәтсіз (бар болуы мүмкін)."))
    groups = await _merged_group_catalog(data)
    selected = set(data.get("selected_teaching_groups") or [])
    selected.add(name)
    await state.update_data(available_groups=groups, selected_teaching_groups=sorted(selected))
    await state.set_state(Form.teaching_groups)
    await message.answer(
        tr(lang, "Группа добавлена. Отметьте нужные и нажмите «Готово».", "Топ қосылды."),
        reply_markup=ikb.get_teaching_groups_kb(lang, groups, selected),
    )


async def _commit_teacher_assignment(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("locale", "ru")
    selected = list(data.get("selected_teaching_groups") or [])
    specialty_wide = bool(data.get("current_assignment_specialty_wide"))
    if not selected and not specialty_wide:
        await callback.answer(
            tr(lang, "Выберите группы или «Вся специальность».", "Топтарды немесе «Бүкіл мамандық» таңдаңыз."),
            show_alert=True,
        )
        return
    assignment = {
        "faculty": str(data.get("faculty", "")),
        "specialty": str(data.get("specialty", "")),
        "specialty_wide": specialty_wide,
        "groups": selected,
    }
    assignments = list(data.get("teaching_assignments") or [])
    assignments.append(assignment)
    flat = flatten_for_profile(assignments)
    await state.update_data(
        teaching_assignments=assignments,
        teaching_groups=flat["teaching_groups"],
        faculty=flat["faculty"],
        specialty=flat["specialty"],
        group=flat["group"],
    )
    summary = assignments_summary(assignments, lang=lang)
    await callback.message.edit_text(
        tr(lang, f"Сохранено:\n{summary}\n\nДобавить ещё кафедру/спец. или завершить?", f"Сақталды:\n{summary}"),
        reply_markup=ikb.get_teacher_assignments_continue_kb(lang),
    )


@router.callback_query(Form.teaching_groups, F.data == CallbackData.REG_GRP_DONE)
async def reg_grp_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    role = str(data.get("role", ""))
    selected = list(data.get("selected_teaching_groups") or [])
    specialty_wide = bool(data.get("current_assignment_specialty_wide"))

    if role == "Преподаватель":
        await _commit_teacher_assignment(callback, state)
        await callback.answer()
        return

    if not selected and not specialty_wide:
        await callback.answer(
            tr(lang, "Выберите хотя бы одну группу.", "Кемінде бір топ таңдаңыз."),
            show_alert=True,
        )
        return
    if specialty_wide and not selected:
        await state.update_data(group="-", teaching_groups=[], specialty_wide=True)
    else:
        await state.update_data(group=selected[0], teaching_groups=selected, specialty_wide=False)
    await _send_preview(callback, state)
    await callback.answer()


@router.callback_query(F.data == CallbackData.REG_ASSIGN_ADD_MORE)
async def reg_assign_add_more(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    await state.update_data(selected_teaching_groups=[], current_assignment_specialty_wide=False)
    text = (
        tr(lang, "Выберите кафедру:", "Кафедраны таңдаңыз:")
        if track != "college"
        else tr(lang, "Выберите бірлестік:", "Бірлестікті таңдаңыз:")
    )
    await callback.message.edit_text(text, reply_markup=ikb.get_faculties_kb(lang, track=track))
    await state.set_state(Form.specialty)
    await callback.answer()


@router.callback_query(F.data == CallbackData.REG_ASSIGN_FINISH)
async def reg_assign_finish(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    assignments = normalize_assignments(data.get("teaching_assignments"))
    if not assignments:
        await callback.answer(tr(lang, "Добавьте хотя бы одну зону.", "Кемінде бір аймақ қосыңыз."), show_alert=True)
        return
    flat = flatten_for_profile(assignments)
    await state.update_data(**flat)
    await _send_preview(callback, state)
    await callback.answer()


@router.callback_query(F.data == CallbackData.REG_ASSIGN_BACK)
async def reg_assign_back(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if is_worker_role(data.get("role")):
        from handlers.registration import _send_preview

        await _send_preview(callback, state)
        await callback.answer()
        return
    track = _track_from_state(data)
    text = (
        tr(lang, "Выберите кафедру:", "Кафедраны таңдаңыз:")
        if track != "college"
        else tr(lang, "Выберите бірлестік:", "Бірлестікті таңдаңыз:")
    )
    await callback.message.edit_text(text, reply_markup=ikb.get_faculties_kb(lang, track=track))
    await state.set_state(Form.specialty)
    await callback.answer()
