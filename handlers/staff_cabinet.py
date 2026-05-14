"""Личный кабинет сотрудника: инлайн-ветки, не пересекающиеся с админ-панелью по правам.

Дорожная карта рабочего места, рассылка подопечным (см. handlers.broadcast_flow) и смена группы
одобренному студенту в пределах ACL can_review.
"""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from core.callbacks import CallbackData
from services.access_control import can_review, get_user_permissions, is_admin
from services.excel_registry import upsert_registration_account_record
from services.registration_store import get_approved_user, update_approved_profile
from states.states import StaffCabinetFlow
from utils.i18n import tr
from utils.validators import MIN_GROUP_NAME_LEN, sanitize_text, validate_min_plaintext

router = Router()


@router.callback_query(F.data == CallbackData.CABINET_WORKPLACE)
async def cabinet_workplace_roadmap(callback: types.CallbackQuery, state: FSMContext):
    """MVP: фиксируем договорённости по продукту без «тихих» заглушек в UX."""
    data = await state.get_data()
    lang = data.get("locale", "ru")
    text = tr(
        lang,
        "Здесь будет рабочее место ответственного: расписание пар, мероприятия со ссылками, "
        "уведомления по группам/специальностям/кафедрам/статусам, переназначение группы студента "
        "(включая «свой вариант» при регистрации) и согласованные сценарии с учителями.\n\n"
        "Сейчас модерация заявок доступна через кнопку «Центр модерации» в этом же сообщении кабинета "
        "или через нижнюю reply-клавиатуру.",
        "Мұнда жауапты қызметкердің жұмыс орны болады: сабақ кестесі, сілтемелі іс-шаралар, "
        "топ/мамандық/кафедра/статус бойынша хабарламалар, студенттің топын қайта тағайындау "
        "(тіркеудегі «өз нұсқаңыз» қоса) және оқытушылармен келісілген сценарийлер.\n\n"
        "Қазір өтінімдерді модерациялау осы кабинет хабарламасындағы «Модерация орталығы» арқылы "
        "немесе төменгі reply-панель арқылы қолжетімді.",
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == CallbackData.STAFF_REASSIGN_START)
async def staff_reassign_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not (is_admin(callback.from_user.id) or get_user_permissions(callback.from_user.id).get("can_review")):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.set_state(StaffCabinetFlow.reassign_enter_user_id)
    await callback.message.answer(
        tr(
            lang,
            "Введите Telegram user id студента (цифры из профиля / ссылки).",
            "Студенттің Telegram user id енгізіңіз (сан).",
        )
    )
    await callback.answer()


@router.message(StaffCabinetFlow.reassign_enter_user_id, F.text)
async def staff_reassign_got_id(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    actor_id = message.from_user.id
    if not (is_admin(actor_id) or get_user_permissions(actor_id).get("can_review")):
        await state.set_state(None)
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(tr(lang, "Нужны только цифры user id.", "Тек сандар керек."))
        return
    uid = int(raw)
    target = get_approved_user(uid)
    if not target:
        await message.answer(tr(lang, "Одобренный пользователь с таким id не найден.", "Мұндай id бойынша мақұлданған пайдаланушы жоқ."))
        return
    if not can_review(actor_id, str(target.get("group", "-")), target.get("specialty")):
        await message.answer(tr(lang, "Нет доступа к этому пользователю по ACL.", "ACL бойынша қолжетімділік жоқ."))
        return
    await state.update_data(reassign_target_id=uid)
    await state.set_state(StaffCabinetFlow.reassign_enter_group)
    await message.answer(
        tr(
            lang,
            f"Текущая группа: {target.get('group', '-')}. Введите новое название группы.",
            f"Ағымдағы топ: {target.get('group', '-')}. Жаңа топ атауын енгізіңіз.",
        )
    )


@router.message(StaffCabinetFlow.reassign_enter_group, F.text)
async def staff_reassign_got_group(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    actor_id = message.from_user.id
    if not (is_admin(actor_id) or get_user_permissions(actor_id).get("can_review")):
        await state.set_state(None)
        return
    uid = data.get("reassign_target_id")
    if not isinstance(uid, int):
        await state.set_state(None)
        return
    group = sanitize_text(message.text or "")
    if not validate_min_plaintext(group, min_len=MIN_GROUP_NAME_LEN):
        await message.answer(
            tr(
                lang,
                f"Слишком короткое название (минимум {MIN_GROUP_NAME_LEN} символа).",
                f"Атау тым қысқа (кемінде {MIN_GROUP_NAME_LEN} таңба).",
            )
        )
        return
    target = get_approved_user(uid)
    if not target:
        await message.answer(tr(lang, "Пользователь пропал из базы, начните заново.", "Пайдаланушы базадан жоғалды, қайта бастаңыз."))
        await state.set_state(None)
        await state.update_data(reassign_target_id=None)
        return
    if not can_review(actor_id, str(target.get("group", "-")), target.get("specialty")):
        await message.answer(tr(lang, "Доступ изменился, операция отменена.", "Қолжетімділік өзгерді, операция болдырылмады."))
        await state.set_state(None)
        await state.update_data(reassign_target_id=None)
        return
    updated = update_approved_profile(uid, group=group)
    if not updated:
        await message.answer(tr(lang, "Не удалось обновить профиль.", "Профильді жаңарту сәтсіз."))
        await state.set_state(None)
        await state.update_data(reassign_target_id=None)
        return
    try:
        upsert_registration_account_record(updated)
    except Exception as err:
        logging.warning("excel sync after group reassign user_id=%s: %s", uid, err)
    await state.set_state(None)
    await state.update_data(reassign_target_id=None)
    await message.answer(tr(lang, f"Группа обновлена: {group}", f"Топ жаңартылды: {group}"))
    try:
        await message.bot.send_message(
            uid,
            tr(
                lang,
                f"Ваша группа в боте обновлена ответственным: {group}",
                f"Боттағы тобыңыз жауапты тараптан жаңартылды: {group}",
            ),
        )
    except Exception as err:
        logging.warning("notify student group change user_id=%s: %s", uid, err)
