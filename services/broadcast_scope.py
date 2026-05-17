"""Фильтрация одобренных пользователей для таргетированных рассылок."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.access_control import can_review, is_admin
from services.registration_store import get_approved_all
from utils.text_links import split_body_and_link

__all__ = (
    "split_body_and_link",
    "filter_approved_users",
    "recipient_telegram_ids",
    "recipients_for_reviewer",
    "deliver_text_broadcast",
)


def filter_approved_users(
    rows: list[dict[str, Any]],
    *,
    track: str | None = None,
    role: str | None = None,
    group: str | None = None,
    faculty: str | None = None,
    specialty: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if track and str(row.get("admission_track", "uni")).strip() != track:
            continue
        if role and str(row.get("role", "")).strip() != role:
            continue
        if group and str(row.get("group", "-")).strip() != group:
            continue
        if faculty and str(row.get("faculty", "-")).strip() != faculty:
            continue
        if specialty and str(row.get("specialty", "-")).strip() != specialty:
            continue
        out.append(row)
    return out


def recipient_telegram_ids(rows: list[dict[str, Any]]) -> list[int]:
    ids: set[int] = set()
    for row in rows:
        uid = int(row.get("tg_user_id") or 0)
        if uid > 0:
            ids.add(uid)
    return sorted(ids)


async def recipients_for_reviewer(reviewer_id: int) -> list[int]:
    rows = await get_approved_all()
    if await is_admin(reviewer_id):
        return recipient_telegram_ids(rows)
    matched: list[dict[str, Any]] = []
    for row in rows:
        if await can_review(reviewer_id, str(row.get("group", "-")), row.get("specialty")):
            matched.append(row)
    return recipient_telegram_ids(matched)


async def deliver_text_broadcast(
    bot: Bot,
    user_ids: list[int],
    text: str,
    *,
    link_url: str | None = None,
    link_button_text: str = "Открыть ссылку",
) -> tuple[int, int]:
    markup: InlineKeyboardMarkup | None = None
    if link_url and link_url.startswith(("http://", "https://")):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=link_button_text, url=link_url)]]
        )
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, reply_markup=markup)
            ok += 1
        except Exception as err:
            fail += 1
            logging.warning("broadcast skip user_id=%s: %s", uid, err)
    return ok, fail
