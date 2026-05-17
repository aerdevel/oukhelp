"""Доставка уведомлений из рабочего места (фильтры + опциональная ссылка)."""

from __future__ import annotations

from typing import Any

from services.access_control import can_review, is_admin
from services.broadcast_scope import filter_approved_users, recipient_telegram_ids
from services.registration_store import get_approved_all


async def resolve_workplace_recipients(
    actor_id: int,
    *,
    track: str | None = None,
    role: str | None = None,
    group: str | None = None,
    specialty: str | None = None,
) -> list[int]:
    rows = await get_approved_all()
    if await is_admin(actor_id):
        matched = filter_approved_users(
            rows,
            track=track,
            role=role,
            group=group,
            faculty=None,
            specialty=specialty,
        )
        return recipient_telegram_ids(matched)

    scoped: list[dict[str, Any]] = []
    for row in rows:
        if not await can_review(actor_id, str(row.get("group", "-")), row.get("specialty")):
            continue
        scoped.append(row)
    matched = filter_approved_users(
        scoped,
        track=track,
        role=role,
        group=group,
        faculty=None,
        specialty=specialty,
    )
    return recipient_telegram_ids(matched)
