from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.resources.text_file.catalog import get_specialties_by_department
from core.resources.text_file.pricing import BASE_TUITION_YEAR, get_discounts
from keyboards import inline as ikb
from services.calculator import calculate_tuition
from utils.number_format import format_int

router = Router()


def _category_prompt(lang: str) -> str:
    if lang == "ru":
        return (
            "Выберите все подходящие льготные категории.\n"
            "Можно выбрать несколько вариантов, затем нажмите «Готово»."
        )
    return (
        "Сәйкес келетін барлық жеңілдік санаттарын таңдаңыз.\n"
        "Бірнеше нұсқаны таңдауға болады, содан кейін «Дайын» түймесін басыңыз."
    )


def _track_from_state(data: dict) -> str:
    return "college" if data.get("admission_track") == "college" or data.get("current_choice") == "Колледж" else "uni"


def _build_categories_kb(lang: str, selected_keys: list[str], track: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected_set = set(selected_keys)
    discounts = get_discounts(lang, track)
    for key, (name, _) in discounts.items():
        mark = "✅ " if key in selected_set else ""
        builder.row(types.InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"{CallbackData.CALC_PREFIX}{key}"))

    done_text = "✅ Готово" if lang == "ru" else "✅ Дайын"
    reset_text = "♻️ Сбросить" if lang == "ru" else "♻️ Тазарту"
    back_text = "🔙 Назад" if lang == "ru" else "🔙 Артқа"
    builder.row(types.InlineKeyboardButton(text=done_text, callback_data=CallbackData.CALC_DONE))
    builder.row(types.InlineKeyboardButton(text=reset_text, callback_data=CallbackData.CALC_RESET))
    builder.row(types.InlineKeyboardButton(text=back_text, callback_data=CallbackData.CALC_START))
    return builder.as_markup()


def _calc_total_discount(selected: list[str], lang: str, track: str) -> tuple[float, list[str]]:
    discounts = get_discounts(lang, track)
    if "none" in selected:
        return 0.0, [discounts["none"][0]]
    unt_keys = [key for key in selected if key.startswith("unt_")]
    other_keys = [key for key in selected if not key.startswith("unt_")]

    unt_rate = 0.0
    unt_label = None
    if unt_keys:
        best_unt = max(unt_keys, key=lambda key: discounts[key][1])
        unt_label, unt_rate = discounts[best_unt]

    other_sum = sum(discounts[key][1] for key in other_keys)
    total_rate = min(1.0, unt_rate + other_sum)

    applied: list[str] = []
    if unt_label:
        applied.append(unt_label)
    applied.extend(discounts[key][0] for key in other_keys)
    return total_rate, applied

@router.callback_query(F.data.in_([CallbackData.FACULTIES, CallbackData.CALC_START]))
async def select_specialty_for_calc(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    back_callback = data.get("calc_back_callback") or CallbackData.LEVEL_UNI
    preset_specialty = data.get("calc_specialty")
    preset_categories = data.get("calc_categories", [])

    # Если расчет открыт из сценария перечня, не заставляем пользователя
    # повторно выбирать кафедру/специальность.
    if preset_specialty and back_callback == CallbackData.DOCS:
        await callback.message.edit_text(
            _category_prompt(lang),
            reply_markup=_build_categories_kb(lang, list(preset_categories), track),
        )
        return

    text = "Выберите кафедру для расчета:" if lang == "ru" else "Есептеу үшін кафедраны таңдаңыз:"
    await callback.message.edit_text(
        text,
        reply_markup=ikb.get_faculties_kb(
            lang,
            prefix=CallbackData.CALC_FAC_PREFIX,
            back_callback=back_callback,
            track=track,
        ),
    )


@router.callback_query(F.data.startswith(CallbackData.CALC_FAC_PREFIX))
async def select_calc_specialty(callback: types.CallbackQuery, state: FSMContext):
    """Показывает специальности выбранной кафедры для расчета."""
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    faculty_idx = callback.data.replace(CallbackData.CALC_FAC_PREFIX, "")
    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    if not faculty_idx.isdigit() or int(faculty_idx) >= len(faculties):
        await callback.message.answer("Ошибка: кафедра не найдена.")
        return

    selected_idx = int(faculty_idx)
    selected_faculty = faculties[selected_idx]
    text = (
        f"Кафедра: {selected_faculty}\n\nВыберите специальность для расчета:"
        if lang == "ru"
        else f"Кафедра: {selected_faculty}\n\nЕсептеу үшін мамандықты таңдаңыз:"
    )
    builder = InlineKeyboardBuilder()
    specialties = specialties_by_department[selected_faculty]
    for spec_idx, spec in enumerate(specialties):
        builder.row(
            types.InlineKeyboardButton(
                text=spec,
                callback_data=f"{CallbackData.CALC_SPEC_PREFIX}{selected_idx}_{spec_idx}",
            )
        )
    back_text = "🔙 Назад" if lang == "ru" else "🔙 Артқа"
    builder.row(
        types.InlineKeyboardButton(
            text=back_text,
            callback_data=CallbackData.CALC_START,
        )
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith(CallbackData.CALC_SPEC_PREFIX))
async def choose_category(callback: types.CallbackQuery, state: FSMContext):
    """Сохраняет специальность и открывает мультивыбор льгот."""
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    payload = callback.data.replace(CallbackData.CALC_SPEC_PREFIX, "")
    if "_" not in payload:
        await callback.message.answer("Ошибка: специальность не найдена.")
        return
    faculty_idx_raw, spec_idx_raw = payload.split("_", 1)
    if not faculty_idx_raw.isdigit() or not spec_idx_raw.isdigit():
        await callback.message.answer("Ошибка: специальность не найдена.")
        return

    specialties_by_department = get_specialties_by_department(lang, track)
    faculties = list(specialties_by_department.keys())
    faculty_idx = int(faculty_idx_raw)
    spec_idx = int(spec_idx_raw)
    if faculty_idx >= len(faculties):
        await callback.message.answer("Ошибка: специальность не найдена.")
        return
    selected_faculty = faculties[faculty_idx]
    specialties = specialties_by_department[selected_faculty]
    if spec_idx >= len(specialties):
        await callback.message.answer("Ошибка: специальность не найдена.")
        return

    await state.update_data(
        calc_faculty=selected_faculty,
        calc_specialty=specialties[spec_idx],
        calc_categories=[],
    )
    await callback.message.edit_text(_category_prompt(lang), reply_markup=_build_categories_kb(lang, [], track))

@router.callback_query(F.data.startswith(CallbackData.CALC_PREFIX))
async def toggle_category(callback: types.CallbackQuery, state: FSMContext):
    """Переключает выбранную льготную категорию."""
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    category_key = callback.data.replace(CallbackData.CALC_PREFIX, "")
    discounts = get_discounts(lang, track)
    if category_key not in discounts:
        await callback.message.answer("Ошибка: категория не найдена.")
        return

    selected = data.get("calc_categories", [])
    if category_key in selected:
        selected.remove(category_key)
    else:
        if category_key == "none":
            selected = ["none"]
        else:
            selected = [key for key in selected if key != "none"]
            selected.append(category_key)
    await state.update_data(calc_categories=selected)
    await callback.message.edit_text(_category_prompt(lang), reply_markup=_build_categories_kb(lang, selected, track))


@router.callback_query(F.data == CallbackData.CALC_RESET)
async def reset_categories(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    await state.update_data(calc_categories=[])
    await callback.message.edit_text(_category_prompt(lang), reply_markup=_build_categories_kb(lang, [], track))


@router.callback_query(F.data == CallbackData.CALC_DONE)
async def show_calculation(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    lang = data.get("locale", "ru")
    track = _track_from_state(data)
    selected = data.get("calc_categories", [])
    if not selected:
        warning = "Сначала выберите хотя бы одну категорию." if lang == "ru" else "Алдымен кемінде бір санатты таңдаңыз."
        await callback.answer(warning, show_alert=True)
        return

    discounts = get_discounts(lang, track)
    rate, applied_labels = _calc_total_discount(selected, lang, track)
    selected_labels = [discounts[key][0] for key in selected]
    year_price, total_price = calculate_tuition(BASE_TUITION_YEAR, rate)
    specialty = data.get("calc_specialty", "-")

    if lang == "ru":
        result = (
            "📊 Калькулятор стоимости обучения\n\n"
            f"🎓 Специальность: {specialty}\n"
            f"🧩 Выбранные категории: {', '.join(selected_labels)}\n"
            f"✅ Учтенные льготы: {', '.join(applied_labels)}\n"
            f"💸 Итоговая скидка: {int(rate*100)}%\n"
            "────────────────────\n"
            f"💰 Стоимость за 1 год: {format_int(year_price)} ₸\n"
            f"🏛 Стоимость за 4 года: {format_int(total_price)} ₸\n\n"
            "ℹ️ Расчет предварительный. Финальная сумма подтверждается приемной комиссией."
        )
    else:
        result = (
            "📊 Оқу құны калькуляторы\n\n"
            f"🎓 Мамандық: {specialty}\n"
            f"🧩 Таңдалған санаттар: {', '.join(selected_labels)}\n"
            f"✅ Ескерілген жеңілдіктер: {', '.join(applied_labels)}\n"
            f"💸 Жалпы жеңілдік: {int(rate*100)}%\n"
            "────────────────────\n"
            f"💰 1 жылға құны: {format_int(year_price)} ₸\n"
            f"🏛 4 жылға құны: {format_int(total_price)} ₸\n\n"
            "ℹ️ Бұл алдын ала есеп. Соңғы соманы қабылдау комиссиясы растайды."
        )

    await state.update_data(
        calc_discount_rate=rate,
        calc_applied_discounts=applied_labels,
        calc_year_price=year_price,
        calc_total_price=total_price,
        calc_completed=True,
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📨 Отправить перечень документов" if lang == "ru" else "📨 Құжаттар тізімін жіберу",
            callback_data=CallbackData.DOCS,
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🔙 Назад" if lang == "ru" else "🔙 Артқа",
            callback_data=CallbackData.CALC_START,
        )
    )
    await callback.message.edit_text(result, reply_markup=builder.as_markup())