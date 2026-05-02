import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import settings
from core.resources.text_file.catalog import SPECIALTIES_BY_DEPARTMENT
from core.resources.text_file.pricing import BASE_TUITION_YEAR
from states.states import DocumentUpload
from core.callbacks import CallbackData
from core.curator_const import is_responsible_user
from core.resources.text_file.texts import MESSAGES
from keyboards import inline as ikb
from keyboards import reply as rkb
from services.documents_store import (
    add_pending_package,
    get_package_for_review,
    mark_package_approved,
    mark_package_denied,
)
from services.audit_log import append_audit_event
from services.documents_files import persist_documents_locally
from services.excel_registry import upsert_applicant_record
from services.notifier import send_documents_package_for_review
from services.registration_store import find_phone_owner, get_approved_user
from services.calculator import calculate_tuition
from utils.i18n import tr
from utils.validators import normalize_phone, sanitize_text, validate_phone

router = Router()
REVIEW_CHAT_ID = settings.moderation_chat_id
DOC_KEY_BY_CODE = {
    "dpl": ("diploma", "Аттестат/диплом"),
    "idc": ("id_card", "Удостоверение личности"),
    "pht": ("photo_3x4", "Фото 3x4"),
    "med": ("medical_075", "Мед. справка 075/у"),
    "ent": ("ent_certificate", "Сертификат ЕНТ"),
}


def _safe_tg_id(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_file_info(message: types.Message) -> dict[str, str]:
    """Нормализует входящий файл к формату, который сохраняется в хранилище."""
    if message.photo:
        return {"kind": "photo", "file_id": message.photo[-1].file_id}
    return {"kind": "document", "file_id": message.document.file_id}


async def _build_docs_package(state: FSMContext, sender: types.User) -> dict:
    """Собирает единый пакет документов из FSM и Telegram-профиля."""
    data = await state.get_data()
    approved_profile = get_approved_user(sender.id) or {}
    return {
        "tg_user_id": sender.id,
        "tg_username": sender.username or "",
        "tg_full_name": sender.full_name,
        "fio": data.get("fio") or approved_profile.get("fio") or sender.full_name,
        "role": data.get("role") or approved_profile.get("role", "-"),
        "group": data.get("group") or approved_profile.get("group", "-"),
        "faculty": data.get("faculty") or approved_profile.get("faculty", "-"),
        "specialty": data.get("specialty") or approved_profile.get("specialty", "-"),
        "course": data.get("course") or approved_profile.get("course", "-"),
        "phone": data.get("phone") or approved_profile.get("phone", "-"),
        "source": data.get("source") or "-",
        "admission_faculty": data.get("admission_faculty") or data.get("calc_faculty") or "-",
        "admission_specialty": data.get("admission_specialty") or data.get("calc_specialty") or "-",
        "calc_discount_rate": float(data.get("calc_discount_rate") or 0.0),
        "calc_year_price": data.get("calc_year_price") or "",
        "calc_total_price": data.get("calc_total_price") or "",
        "calc_applied_discounts": data.get("calc_applied_discounts") or [],
        "documents": {
            "diploma": data.get("doc_diploma"),
            "id_card": data.get("doc_id_card"),
            "photo_3x4": data.get("doc_photo_3x4"),
            "medical_075": data.get("doc_medical_075"),
            "ent_certificate": data.get("doc_ent_certificate"),
        },
    }


async def _ask_diploma_step(target: types.Message | types.CallbackQuery, lang: str) -> None:
    """Единая точка старта загрузки документов после сбора профиля."""
    text = tr(
        lang,
        "Шаг 1: Отправьте фото или скан вашего Аттестата/Диплома:",
        "1-қадам: Аттестат/Диплом фотосын немесе сканерін жіберіңіз:",
    )
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=ikb.get_back_kb(lang, CallbackData.DOCS))
    else:
        await target.answer(text, reply_markup=ikb.get_back_kb(lang, CallbackData.DOCS))


async def _ask_faculty_step(target: types.Message | types.CallbackQuery, lang: str) -> None:
    text = tr(lang, "Выберите кафедру поступления:", "Түсетін кафедраны таңдаңыз:")
    kb = ikb.get_faculties_kb(lang, prefix=CallbackData.DOC_FAC_PREFIX, back_callback=CallbackData.DOCS)
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == CallbackData.DOCS)
async def show_docs_list(callback: types.CallbackQuery, state: FSMContext):
    """Показывает чек-лист документов и переводит пользователя к загрузке."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    
    text = MESSAGES[lang]["docs_list"]
    
    await callback.message.edit_text(text, reply_markup=ikb.get_docs_list_kb(lang))
    await callback.answer()

@router.callback_query(F.data == CallbackData.START_UPLOAD)
async def start_upload(callback: types.CallbackQuery, state: FSMContext):
    """Инициализирует пошаговый сценарий загрузки документов."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    approved_profile = get_approved_user(callback.from_user.id) or {}
    fio = sanitize_text(str(data.get("fio") or approved_profile.get("fio", "")))
    phone = str(data.get("phone") or approved_profile.get("phone", "")).strip()

    # Для абитуриента анкета не обязательна: если данных нет, собираем их прямо в сценарии документов.
    if not fio or fio == "-":
        await state.set_state(DocumentUpload.waiting_for_fio)
        await callback.message.edit_text(
            tr(
                lang,
                "Введите ФИО для отправки пакета документов:",
                "Құжаттар пакетін жіберу үшін аты-жөніңізді енгізіңіз:",
            ),
            reply_markup=ikb.get_back_kb(lang, CallbackData.DOCS),
        )
        await callback.answer()
        return

    if not validate_phone(phone):
        await state.update_data(fio=fio)
        await state.set_state(DocumentUpload.waiting_for_phone)
        prompt = tr(
            lang,
            "Отправьте номер телефона (можно кнопкой контакта ниже):",
            "Телефон нөмірін жіберіңіз (төмендегі контакт батырмасын пайдалануға болады):",
        )
        await callback.message.edit_text(
            prompt,
            reply_markup=ikb.get_back_kb(lang, CallbackData.DOCS),
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
        return

    await state.update_data(fio=fio, phone=normalize_phone(phone) or phone)
    admission_specialty = data.get("admission_specialty") or data.get("calc_specialty")
    if not admission_specialty:
        await state.set_state(DocumentUpload.waiting_for_faculty)
        await _ask_faculty_step(callback, lang)
        await callback.answer()
        return
    if not bool(data.get("calc_completed")):
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text=tr(lang, "💰 Выбрать льготы и рассчитать цену", "💰 Жеңілдіктерді таңдап, бағасын есептеу"),
                callback_data=CallbackData.CALC_START,
            )
        )
        builder.row(types.InlineKeyboardButton(text=tr(lang, "🔙 К перечню", "🔙 Тізімге"), callback_data=CallbackData.DOCS))
        await callback.message.edit_text(
            tr(
                lang,
                "Перед отправкой перечня выберите льготы в калькуляторе и получите итоговую стоимость.",
                "Тізімді жібермес бұрын калькуляторда жеңілдіктерді таңдап, соңғы құнын есептеңіз.",
            ),
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return
    if not data.get("source"):
        await state.set_state(DocumentUpload.waiting_for_source)
        await callback.message.edit_text(
            tr(
                lang,
                "Укажите, пожалуйста, откуда вы узнали об университете:",
                "Университет туралы қайдан білгеніңізді жазыңыз:",
            ),
            reply_markup=ikb.get_back_kb(lang, CallbackData.DOCS),
        )
        await callback.answer()
        return
    if data.get("source") and admission_specialty:
        await state.set_state(DocumentUpload.waiting_for_diploma)
        await _ask_diploma_step(callback, lang)
        await callback.answer()
        return
    await callback.answer()


@router.message(DocumentUpload.waiting_for_fio)
async def docs_collect_fio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    fio = sanitize_text(message.text or "")
    if len(fio) < 5:
        await message.answer(
            tr(
                lang,
                "Укажите, пожалуйста, ФИО полностью:",
                "Толық аты-жөніңізді көрсетіңіз:",
            )
        )
        return
    await state.update_data(fio=fio)
    await state.set_state(DocumentUpload.waiting_for_phone)
    await message.answer(
        tr(
            lang,
            "Отправьте номер телефона (можно кнопкой контакта ниже):",
            "Телефон нөмірін жіберіңіз (төмендегі контакт батырмасын пайдалануға болады):",
        ),
        reply_markup=rkb.get_phone_kb(lang),
    )


@router.message(DocumentUpload.waiting_for_phone)
async def docs_collect_phone_common(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    logging.info(
        "docs_phone_step update: user_id=%s has_contact=%s text=%s",
        message.from_user.id if message.from_user else "-",
        bool(message.contact),
        bool(message.text),
    )
    if message.contact and message.contact.user_id and int(message.contact.user_id) != int(message.from_user.id):
        await message.answer(
            tr(
                lang,
                "Отправьте, пожалуйста, свой контакт через кнопку ниже.",
                "Төмендегі батырма арқылы өз контактіңізді жіберіңіз.",
            ),
            reply_markup=rkb.get_phone_kb(lang),
        )
        return
    raw_phone = message.contact.phone_number if message.contact else (message.text or "")
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
    normalized_phone = normalize_phone(str(raw_phone))
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
    await state.set_state(DocumentUpload.waiting_for_faculty)
    await message.answer(tr(lang, "✅ Номер принят.", "✅ Нөмір қабылданды."), reply_markup=ReplyKeyboardRemove())
    await message.answer(
        tr(
            lang,
            f"Ваш номер сохранен: {normalized_phone}",
            f"Нөміріңіз сақталды: {normalized_phone}",
        )
    )
    await _ask_faculty_step(message, lang)


@router.message(DocumentUpload.waiting_for_source)
async def docs_collect_source(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    source = sanitize_text(message.text or "")
    if len(source) < 3:
        await message.answer(tr(lang, "Уточните источник (минимум 3 символа).", "Дереккөзді нақтылаңыз (кемінде 3 таңба)."))
        return
    await state.update_data(source=source)
    await state.set_state(DocumentUpload.waiting_for_diploma)
    await _ask_diploma_step(message, lang)


@router.callback_query(DocumentUpload.waiting_for_faculty, F.data.startswith(CallbackData.DOC_FAC_PREFIX))
async def docs_select_faculty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    raw_idx = callback.data.replace(CallbackData.DOC_FAC_PREFIX, "")
    faculties = list(SPECIALTIES_BY_DEPARTMENT[lang].keys())
    if not raw_idx.isdigit() or int(raw_idx) >= len(faculties):
        await callback.answer("Некорректный выбор кафедры.", show_alert=True)
        return
    idx = int(raw_idx)
    selected_faculty = faculties[idx]
    await state.update_data(admission_faculty=selected_faculty)
    builder = InlineKeyboardBuilder()
    for spec_idx, specialty in enumerate(SPECIALTIES_BY_DEPARTMENT[lang][selected_faculty]):
        builder.row(
            types.InlineKeyboardButton(
                text=specialty,
                callback_data=f"{CallbackData.DOC_SPEC_PREFIX}{idx}_{spec_idx}",
            )
        )
    builder.row(types.InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Артқа", callback_data=CallbackData.DOCS))
    await state.set_state(DocumentUpload.waiting_for_specialty)
    await callback.message.edit_text(
        tr(lang, "Выберите специальность поступления:", "Түсетін мамандықты таңдаңыз:"),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(DocumentUpload.waiting_for_specialty, F.data.startswith(CallbackData.DOC_SPEC_PREFIX))
async def docs_select_specialty(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    payload = callback.data.replace(CallbackData.DOC_SPEC_PREFIX, "")
    fac_raw, _, spec_raw = payload.partition("_")
    faculties = list(SPECIALTIES_BY_DEPARTMENT[lang].keys())
    if not fac_raw.isdigit() or not spec_raw.isdigit():
        await callback.answer("Некорректный выбор специальности.", show_alert=True)
        return
    fac_idx = int(fac_raw)
    spec_idx = int(spec_raw)
    if fac_idx >= len(faculties):
        await callback.answer("Некорректный выбор специальности.", show_alert=True)
        return
    selected_faculty = faculties[fac_idx]
    specialties = SPECIALTIES_BY_DEPARTMENT[lang][selected_faculty]
    if spec_idx >= len(specialties):
        await callback.answer("Некорректный выбор специальности.", show_alert=True)
        return
    selected_specialty = specialties[spec_idx]
    year_price, total_price = calculate_tuition(BASE_TUITION_YEAR, 0.0)
    await state.update_data(
        admission_faculty=selected_faculty,
        admission_specialty=selected_specialty,
        calc_faculty=selected_faculty,
        calc_specialty=selected_specialty,
        calc_back_callback=CallbackData.DOCS,
        calc_categories=[],
        calc_discount_rate=0.0,
        calc_year_price=year_price,
        calc_total_price=total_price,
        calc_applied_discounts=[],
        calc_completed=False,
    )
    await state.set_state(DocumentUpload.waiting_for_specialty)
    text = tr(
        lang,
        f"Специальность выбрана: {selected_specialty}\n"
        f"Базовая стоимость: {year_price:,} ₸/год, {total_price:,} ₸ за 4 года.\n"
        "Теперь выберите льготы в разделе «Льготы и расчет цены», чтобы получить итоговую стоимость.",
        f"Мамандық таңдалды: {selected_specialty}\n"
        f"Базалық құны: {year_price:,} ₸/жыл, {total_price:,} ₸ (4 жыл).\n"
        "Енді соңғы бағаны алу үшін «Жеңілдік пен баға есебі» бөлімінде жеңілдіктерді таңдаңыз.",
    ).replace(",", " ")
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text=tr(lang, "💸 Льготы и расчет цены", "💸 Жеңілдік пен баға есебі"),
            callback_data=CallbackData.CALC_START,
        )
    )
    builder.row(types.InlineKeyboardButton(text=tr(lang, "🔙 К перечню", "🔙 Тізімге"), callback_data=CallbackData.DOCS))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.message(DocumentUpload.waiting_for_diploma, F.photo | F.document)
async def process_diploma(message: types.Message, state: FSMContext):
    """Обрабатывает аттестат/диплом и запрашивает удостоверение личности."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.update_data(doc_diploma=_extract_file_info(message))
    
    await state.set_state(DocumentUpload.waiting_for_id)
    text = tr(lang, "✅ Получено! Шаг 2: Отправьте Удостоверение личности:", "✅ Қабылданды! 2-қадам: Жеке куәлікті жіберіңіз:")
    await message.answer(text)

@router.message(DocumentUpload.waiting_for_id, F.photo | F.document)
async def process_id(message: types.Message, state: FSMContext):
    """Обрабатывает удостоверение и запрашивает фото 3x4."""
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(doc_id_card=_extract_file_info(message))
    
    await state.set_state(DocumentUpload.waiting_for_photo)
    text = tr(lang, "✅ Шаг 3: Отправьте Ваше Фото 3х4:", "✅ 3-қадам: 3х4 фотоңызды жіберіңіз:")
    await message.answer(text)

@router.message(DocumentUpload.waiting_for_photo, F.photo)
async def process_photo_3x4(message: types.Message, state: FSMContext):
    """Обрабатывает фото и запрашивает медицинскую справку."""
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(doc_photo_3x4=_extract_file_info(message))
    
    await state.set_state(DocumentUpload.waiting_for_medical)
    text = tr(lang, "✅ Шаг 4: Отправьте Справку 075/у:", "✅ 4-қадам: 075/у анықтамасын жіберіңіз:")
    await message.answer(text)

@router.message(DocumentUpload.waiting_for_medical, F.photo | F.document)
async def process_medical(message: types.Message, state: FSMContext):
    """Обрабатывает медицинскую справку и запрашивает сертификат ЕНТ."""
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(doc_medical_075=_extract_file_info(message))
    
    await state.set_state(DocumentUpload.waiting_for_ent)
    text = tr(lang, "✅ Шаг 5: Отправьте Сертификат ЕНТ:", "✅ 5-қадам: ҰБТ сертификатын жіберіңіз:")
    await message.answer(text)

@router.message(DocumentUpload.waiting_for_ent, F.photo | F.document)
async def process_ent_preview(message: types.Message, state: FSMContext):
    """Показывает финальное подтверждение перед отправкой пакета в комиссию."""
    data = await state.get_data()
    lang = data.get("locale", "ru")

    await state.update_data(doc_ent_certificate=_extract_file_info(message))

    text = tr(
        lang,
        "Вы загрузили все документы. Отправить их в приемную комиссию?",
        "Сіз барлық құжаттарды жүктедіңіз. Қабылдау комиссиясына жібереміз бе?",
    )
    await state.update_data(documents_consent=False)
    await message.answer(text, reply_markup=ikb.get_docs_confirm_kb(lang, consent_given=False))


@router.callback_query(F.data == CallbackData.DOC_CONSENT)
async def confirm_pd_consent(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.update_data(documents_consent=True)
    await callback.message.edit_reply_markup(reply_markup=ikb.get_docs_confirm_kb(lang, consent_given=True))
    await callback.answer("Согласие сохранено." if lang == "ru" else "Келісім сақталды.")


@router.callback_query(F.data == CallbackData.DOC_POLICY_INFO)
async def policy_not_configured(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    text = tr(
        lang,
        "Политика обработки ПД:\n"
        "1) Мы собираем только данные, нужные для приемной кампании.\n"
        "2) Данные доступны только уполномоченным сотрудникам.\n"
        "3) Вы можете запросить выгрузку или удаление данных командами /my_data и /delete_me.\n"
        "4) Для публикации официальной версии укажите PRIVACY_POLICY_URL в .env.",
        "Дербес деректерді өңдеу саясаты:\n"
        "1) Тек қабылдау процесіне қажет деректер жиналады.\n"
        "2) Деректерге тек уәкілетті қызметкерлер қол жеткізеді.\n"
        "3) /my_data және /delete_me арқылы деректерді алу/жою сұрауын бере аласыз.\n"
        "4) Ресми нұсқаны жариялау үшін .env ішінде PRIVACY_POLICY_URL орнатыңыз.",
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == CallbackData.CONFIRM_DOCS)
async def finalize_documents(callback: types.CallbackQuery, state: FSMContext):
    """Фиксирует пакет в очереди и отправляет его на модерацию."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not bool(data.get("documents_consent")):
        await callback.answer(
            tr(
                lang,
                "Подтвердите согласие на обработку персональных данных перед отправкой.",
                "Жібермес бұрын дербес деректерді өңдеуге келісімді растаңыз.",
            ),
            show_alert=True,
        )
        return
    package = await _build_docs_package(state, callback.from_user)
    package["consent_personal_data"] = True
    if not package.get("fio") or package.get("fio") == "-" or not package.get("phone") or package.get("phone") == "-":
        await callback.answer(
            tr(
                lang,
                "Нужно указать ФИО и телефон в анкете перед отправкой документов.",
                "Құжат жіберер алдында анкетада аты-жөні мен телефон толтырылуы керек.",
            ),
            show_alert=True,
        )
        return
    await persist_documents_locally(callback.bot, package)
    # Сохраняем пакет уже после обогащения local_path, чтобы пути не терялись при последующих апдейтах.
    add_pending_package(package)
    stored_pending = get_package_for_review(callback.from_user.id) or {}
    package["submit_attempt"] = int(stored_pending.get("submit_attempt", 1) or 1)
    # Сразу фиксируем запись в реестре как pending, чтобы приемная видела ФИО/телефон до решения.
    package["review_status"] = "pending"
    excel_result = upsert_applicant_record(package)
    package["excel_applicant_saved"] = bool(excel_result.get("ok"))
    package["excel_applicant_was_existing"] = bool(excel_result.get("was_existing"))
    await send_documents_package_for_review(callback.bot, package)
    
    success_text = tr(
        lang,
        "✅ Все документы успешно переданы в приемную комиссию!\n\n Ожидайте ответа, мы скоро свяжемся с вами.",
        "✅ Барлық құжаттар қабылдау комиссиясына сәтті тапсырылды!\n\n Жауап күтіңіз, біз сізге жақын арада хабарласамыз.",
    )
    await callback.message.edit_text(success_text, reply_markup=ikb.get_docs_done_kb(lang))
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.DOC_REVIEW_PREFIX))
async def review_documents_package(callback: types.CallbackQuery):
    """Обрабатывает решение модератора по загруженному пакету."""
    if callback.message.chat.id != REVIEW_CHAT_ID:
        await callback.answer("Действие доступно только в чате приемной комиссии.", show_alert=True)
        return
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    payload = callback.data.replace(CallbackData.DOC_REVIEW_PREFIX, "")
    action, _, tg_id_raw = payload.partition("_")
    if not tg_id_raw.isdigit():
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    tg_user_id = int(tg_id_raw)
    if action == "approve":
        package = mark_package_approved(tg_user_id, callback.from_user.id, callback.from_user.username)
        if not package:
            await callback.answer("Пакет уже обработан.", show_alert=True)
            return
        upsert_applicant_record(package)
        await callback.message.answer(f"✅ Пакет пользователя {tg_user_id} принят и сохранен в реестр.")
        try:
            await callback.bot.send_message(
                tg_user_id,
                "✅ Ваш пакет документов принят приемной комиссией.",
            )
        except Exception as err:
            logging.warning("Не удалось уведомить пользователя %s об одобрении пакета: %s", tg_user_id, err)
        append_audit_event(
            "documents_approved",
            callback.from_user.id,
            {"tg_user_id": tg_user_id, "review_chat_id": callback.message.chat.id},
        )
    elif action == "deny":
        package = mark_package_denied(tg_user_id, callback.from_user.id, callback.from_user.username)
        if not package:
            await callback.answer("Пакет уже обработан.", show_alert=True)
            return
        await callback.message.answer(f"❌ Пакет пользователя {tg_user_id} отклонен.")
        try:
            await callback.bot.send_message(
                tg_user_id,
                "❌ Пакет документов отклонен. Проверьте данные и отправьте снова.",
            )
        except Exception as err:
            logging.warning("Не удалось уведомить пользователя %s об отклонении пакета: %s", tg_user_id, err)
        append_audit_event(
            "documents_denied",
            callback.from_user.id,
            {"tg_user_id": tg_user_id, "review_chat_id": callback.message.chat.id},
        )
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.DOC_FILES_PREFIX))
async def open_documents_menu(callback: types.CallbackQuery):
    """Открывает список документов пакета отдельным действием из карточки заявки."""
    if callback.message.chat.id != REVIEW_CHAT_ID:
        await callback.answer("Действие доступно только в чате приемной комиссии.", show_alert=True)
        return
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    tg_id_raw = callback.data.replace(CallbackData.DOC_FILES_PREFIX, "")
    if not tg_id_raw.isdigit():
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    tg_user_id = int(tg_id_raw)
    package = get_package_for_review(tg_user_id)
    if not package:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    title = (
        "📂 Документы абитуриента\n"
        f"👤 {package.get('fio', '-')}\n"
        f"📞 {package.get('phone', '-')}\n"
        f"🆔 {tg_user_id}"
    )
    await callback.message.answer(title, reply_markup=ikb.get_documents_files_kb(tg_user_id))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.DOC_FILE_PREFIX))
async def open_review_document(callback: types.CallbackQuery):
    """Открывает конкретный документ пакета прямо в чате модерации."""
    if callback.message.chat.id != REVIEW_CHAT_ID:
        await callback.answer("Действие доступно только в чате приемной комиссии.", show_alert=True)
        return
    if not is_responsible_user(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    payload = callback.data.replace(CallbackData.DOC_FILE_PREFIX, "")
    tg_id_raw, _, doc_code = payload.partition("_")
    if not tg_id_raw.isdigit() or doc_code not in DOC_KEY_BY_CODE:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    tg_user_id = int(tg_id_raw)
    package = get_package_for_review(tg_user_id)
    if not package:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    doc_key, doc_title = DOC_KEY_BY_CODE[doc_code]
    doc_info = package.get("documents", {}).get(doc_key)
    if not doc_info:
        await callback.answer("Документ не загружен.", show_alert=True)
        return

    caption_lines = [
        f"📌 {doc_title}",
        f"👤 {package.get('fio', '-')}",
        f"📞 {package.get('phone', '-')}",
        f"🆔 {tg_user_id}",
    ]
    if package.get("tg_username"):
        caption_lines.append(f"🔗 @{package.get('tg_username')}")
    caption = "\n".join(caption_lines)
    if doc_info.get("kind") == "photo":
        await callback.bot.send_photo(callback.message.chat.id, doc_info["file_id"], caption=caption)
    else:
        await callback.bot.send_document(callback.message.chat.id, doc_info["file_id"], caption=caption)
    await callback.answer()
