"""Таргетированные рассылки одобренным пользователям (админ и уполномоченные can_broadcast).

Фильтры: трек (uni/college) и роль. Тело сообщения + опциональная строка LINK: URL.
Отдельный вход для ответственных: рассылка только подопечным по ACL can_review.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.callbacks import CallbackData
from core.curator_const import is_responsible_user
from services.access_control import can_use_targeted_broadcast
from services.broadcast_scope import (
    deliver_text_broadcast,
    filter_approved_users,
    recipient_telegram_ids,
    recipients_for_reviewer,
    split_body_and_link,
)
from services.registration_store import get_approved_all
from states.states import BroadcastFlow
from utils.i18n import tr

router = Router()

_ROLE_SLUG_TO_RU: dict[str, str | None] = {
    "stud": "Студент",
    "grad": "Выпускник",
    "work": "Работник",
    "teach": "Преподаватель",
    "clr": None,
}


def _filter_summary(lang: str, bf: dict[str, Any]) -> str:
    if not any(bf.get(k) for k in ("track", "role", "group", "faculty", "specialty")):
        return tr(lang, "Аудитория: все одобренные пользователи.", "Аудитория: барлық мақұлданған пайдаланушылар.")
    parts: list[str] = []
    if bf.get("track"):
        parts.append(tr(lang, f"Трек: {bf['track']}", f"Трек: {bf['track']}"))
    if bf.get("role"):
        parts.append(tr(lang, f"Статус: {bf['role']}", f"Статус: {bf['role']}"))
    if bf.get("faculty"):
        parts.append(tr(lang, f"Кафедра/бірлестік: {bf['faculty']}", f"Кафедра/бірлестік: {bf['faculty']}"))
    if bf.get("specialty"):
        parts.append(tr(lang, f"Специальность: {bf['specialty']}", f"Мамандық: {bf['specialty']}"))
    if bf.get("group"):
        parts.append(tr(lang, f"Группа: {bf['group']}", f"Топ: {bf['group']}"))
    return "\n".join(parts)


def _broadcast_filter_keyboard(lang: str) -> types.InlineKeyboardMarkup:
    p = CallbackData.BROADCAST_FILTER_PREFIX
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text=tr(lang, "Трек: универ", "Трек: универ"), callback_data=f"{p}track_uni"),
        types.InlineKeyboardButton(text=tr(lang, "Трек: колледж", "Трек: колледж"), callback_data=f"{p}track_college"),
        types.InlineKeyboardButton(text=tr(lang, "Трек: любой", "Трек: кез келген"), callback_data=f"{p}track_clear"),
    )
    b.row(
        types.InlineKeyboardButton(text=tr(lang, "Роль: студент", "Рөл: студент"), callback_data=f"{p}role_stud"),
        types.InlineKeyboardButton(text=tr(lang, "Роль: выпускник", "Рөл: түлек"), callback_data=f"{p}role_grad"),
    )
    b.row(
        types.InlineKeyboardButton(text=tr(lang, "Роль: работник", "Рөл: қызметкер"), callback_data=f"{p}role_work"),
        types.InlineKeyboardButton(text=tr(lang, "Роль: препод", "Рөл: оқытушы"), callback_data=f"{p}role_teach"),
        types.InlineKeyboardButton(text=tr(lang, "Роль: любая", "Рөл: кез келген"), callback_data=f"{p}role_clr"),
    )
    b.row(
        types.InlineKeyboardButton(text=tr(lang, "Готово — ввести текст", "Дайын — мәтін енгізу"), callback_data=f"{p}done"),
        types.InlineKeyboardButton(text=tr(lang, "Сбросить фильтр", "Сүзгіні тазалау"), callback_data=f"{p}reset"),
    )
    b.row(types.InlineKeyboardButton(text=tr(lang, "Отмена", "Болдырмау"), callback_data=CallbackData.BROADCAST_ABORT))
    return b.as_markup()


@router.callback_query(F.data == CallbackData.ADMIN_PANEL_BROADCAST)
async def admin_open_broadcast(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not can_use_targeted_broadcast(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.update_data(bc_mode="admin", bc_filter={})
    await state.set_state(None)
    head = tr(
        lang,
        "Рассылка по одобренным аккаунтам. Выберите фильтры (можно не выбирать — тогда уйдёт всем).\n\n",
        "Мақұлданған аккаунттарға хабарлама. Сүзгілерді таңдаңыз (таңдамасаңыз — барлығына).\n\n",
    )
    await callback.message.answer(head + _filter_summary(lang, {}), reply_markup=_broadcast_filter_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data.startswith(CallbackData.BROADCAST_FILTER_PREFIX))
async def admin_broadcast_filter(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not can_use_targeted_broadcast(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    if data.get("bc_mode") != "admin":
        await callback.answer(
            tr(
                lang,
                "Сначала откройте рассылку заново (кнопка в админ-панели или в «Мой кабинет»).",
                "Алдымен хабарламаны қайта ашыңыз (админ панелі немесе «Жеке кабинет»).",
            ),
            show_alert=True,
        )
        return
    raw = callback.data.replace(CallbackData.BROADCAST_FILTER_PREFIX, "")
    bf: dict[str, Any] = dict(data.get("bc_filter") or {})

    if raw == "reset":
        bf = {}
    elif raw == "done":
        await state.set_state(BroadcastFlow.waiting_message)
        await callback.message.edit_text(
            tr(
                lang,
                "Пришлите текст рассылки одним сообщением.\n\n"
                "Чтобы добавить кнопку-ссылку, в конце добавьте строку:\n"
                "LINK: https://example.com",
                "Хабарламаны бір хабарламада жіберіңіз.\n\n"
                "Сілтеме батырмасы үшін соңына жол қосыңыз:\n"
                "LINK: https://example.com",
            )
            + "\n\n"
            + _filter_summary(lang, bf),
        )
        await callback.answer()
        return
    elif raw == "track_uni":
        bf["track"] = "uni"
    elif raw == "track_college":
        bf["track"] = "college"
    elif raw == "track_clear":
        bf.pop("track", None)
    elif raw.startswith("role_"):
        slug = raw.replace("role_", "")
        role_val = _ROLE_SLUG_TO_RU.get(slug)
        if role_val is None:
            bf.pop("role", None)
        else:
            bf["role"] = role_val

    await state.update_data(bc_filter=bf)
    head = tr(
        lang,
        "Рассылка: настройте фильтры и нажмите «Готово — ввести текст».\n\n",
        "Хабарлама: сүзгілерді баптаңыз да «Дайын — мәтін енгізу» басыңыз.\n\n",
    )
    await callback.message.edit_text(head + _filter_summary(lang, bf), reply_markup=_broadcast_filter_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data == CallbackData.BROADCAST_ABORT)
async def broadcast_abort(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    await state.set_state(None)
    await state.update_data(bc_mode=None, bc_filter=None)
    await callback.message.edit_text(tr(lang, "Рассылка отменена.", "Хабарлама болдырылмады."))
    await callback.answer()


@router.callback_query(F.data == CallbackData.STAFF_NOTIFY)
async def staff_notify_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    if not is_responsible_user(callback.from_user.id):
        await callback.answer(tr(lang, "Нет доступа.", "Қолжетімділік жоқ."), show_alert=True)
        return
    await state.update_data(bc_mode="staff_review", bc_filter={})
    await state.set_state(BroadcastFlow.waiting_message)
    n = len(recipients_for_reviewer(callback.from_user.id))
    await callback.message.answer(
        tr(
            lang,
            f"Сообщение уйдёт подопечным по вашим правам модерации (оценочно получателей: {n}).\n\n"
            "Пришлите текст одним сообщением. Ссылка-кнопка: строка LINK: https://... в конце.\n"
            "Отменить можно через «Главное меню» в reply-клавиатуре.",
            f"Хабарлама модерация құқығыңыз бойынша тәлімгерлеріңізге жіберіледі (шамамен {n} адам).\n\n"
            "Мәтінді бір хабарламада жіберіңіз. Сілтеме: LINK: https://... жолы соңында.\n"
            "Болдырмау үшін reply-панельдегі «Басты мәзір» пайдаланыңыз.",
        )
    )
    await callback.answer()


@router.message(BroadcastFlow.waiting_message, F.text)
async def broadcast_receive_body(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("locale", "ru")
    mode = data.get("bc_mode")
    if mode == "admin":
        if not can_use_targeted_broadcast(message.from_user.id):
            await state.set_state(None)
            return
    elif mode == "staff_review":
        if not is_responsible_user(message.from_user.id):
            await state.set_state(None)
            return
    else:
        await state.set_state(None)
        return

    body, link = split_body_and_link(message.text or "")
    if not body.strip():
        await message.answer(tr(lang, "Пустой текст, пришлите ещё раз.", "Бос мәтін, қайта жіберіңіз."))
        return

    if mode == "admin":
        bf = data.get("bc_filter") or {}
        rows = filter_approved_users(
            get_approved_all(),
            track=bf.get("track"),
            role=bf.get("role"),
            group=bf.get("group"),
            faculty=bf.get("faculty"),
            specialty=bf.get("specialty"),
        )
        targets = recipient_telegram_ids(rows)
    else:
        targets = recipients_for_reviewer(message.from_user.id)

    if not targets:
        await message.answer(tr(lang, "Нет получателей по текущим условиям.", "Алушылар жоқ."))
        await state.set_state(None)
        await state.update_data(bc_mode=None, bc_filter=None)
        return

    link_label = tr(lang, "Открыть ссылку", "Сілтемені ашу")
    ok, fail = await deliver_text_broadcast(message.bot, targets, body, link_url=link, link_button_text=link_label)
    await message.answer(
        tr(
            lang,
            f"Готово. Доставлено: {ok}, ошибок: {fail}.",
            f"Дайын. Жеткізілді: {ok}, қате: {fail}.",
        )
    )
    logging.info(
        "broadcast actor=%s mode=%s recipients=%s ok=%s fail=%s",
        message.from_user.id,
        mode,
        len(targets),
        ok,
        fail,
    )
    await state.set_state(None)
    await state.update_data(bc_mode=None, bc_filter=None)
