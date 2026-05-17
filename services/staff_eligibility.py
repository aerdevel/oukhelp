"""Кто может открыть «Рабочее место» (расписание, мероприятия, уведомления)."""

from __future__ import annotations

from services.access_control import get_user_permissions, is_admin
from services.registration_store import get_approved_user

_STAFF_ROLES = frozenset({"Работник", "Преподаватель"})


async def can_use_workplace(user_id: int) -> bool:
    if await is_admin(user_id):
        return True
    perms = await get_user_permissions(user_id)
    if perms.get("can_review"):
        return True
    profile = await get_approved_user(user_id)
    if not profile:
        return False
    return str(profile.get("role", "")).strip() in _STAFF_ROLES
