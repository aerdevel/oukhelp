"""ACL и права сотрудников (PostgreSQL). Бизнес-правила здесь; SQL — в db.repositories."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.resources.text_file.catalog import SPECIALTIES_BY_TRACK, get_all_specialties as catalog_get_all_specialties
from db.database import session_scope
from db import repositories as repo
from db.serialization import access_profile_to_dict
from db.models import AccessProfile

ALL_GROUPS = "*"


def is_primary_admin(user_id: int) -> bool:
    return int(user_id) == int(settings.admin_id)


async def _seed_defaults_if_empty(session) -> None:
    from sqlalchemy import func, select

    count = await session.scalar(select(func.count()).select_from(AccessProfile))
    if count and count > 0:
        return
    for admin_user_id in settings.admin_list:
        session.add(
            AccessProfile(
                user_id=int(admin_user_id),
                can_notify=True,
                can_review=True,
                can_broadcast=True,
                is_admin=True,
                faculties=[ALL_GROUPS],
                groups=[ALL_GROUPS],
                specialties=[ALL_GROUPS],
            )
        )
    session.add(
        AccessProfile(
            user_id=int(settings.priemka_id),
            can_notify=True,
            can_review=True,
            can_broadcast=False,
            is_admin=False,
            faculties=[ALL_GROUPS],
            groups=[ALL_GROUPS],
            specialties=[ALL_GROUPS],
        )
    )


async def is_admin(user_id: int) -> bool:
    if int(user_id) in {int(x) for x in settings.admin_list}:
        return True
    async with session_scope() as session:
        await _seed_defaults_if_empty(session)
        row = await repo.access_get(session, user_id)
        return bool(row and row.is_admin)


async def ensure_user(user_id: int) -> dict[str, Any]:
    async with session_scope() as session:
        await _seed_defaults_if_empty(session)
        row = await repo.access_ensure(session, user_id)
        return access_profile_to_dict(row)


async def set_user_permissions(
    actor_id: int,
    target_user_id: int,
    *,
    can_notify: bool | None = None,
    can_review: bool | None = None,
    can_broadcast: bool | None = None,
    groups: list[str] | None = None,
    specialties: list[str] | None = None,
    faculties: list[str] | None = None,
    is_admin_flag: bool | None = None,
) -> None:
    if not await is_admin(actor_id):
        raise PermissionError("Недостаточно прав для изменения доступов.")
    if is_admin_flag is not None and not is_primary_admin(actor_id):
        raise PermissionError("Только главный администратор может назначать других админов.")
    if is_admin_flag is False and is_primary_admin(target_user_id):
        raise PermissionError("Нельзя снять права главного администратора.")
    async with session_scope() as session:
        row = await repo.access_ensure(session, target_user_id)
        if can_notify is not None:
            row.can_notify = bool(can_notify)
        if can_review is not None:
            row.can_review = bool(can_review)
        if can_broadcast is not None:
            row.can_broadcast = bool(can_broadcast)
        if groups is not None:
            row.groups = [g.strip() for g in groups if g.strip()]
        if specialties is not None:
            row.specialties = [s.strip() for s in specialties if s.strip()]
        if faculties is not None:
            row.faculties = [f.strip() for f in faculties if f.strip()]
        if is_admin_flag is not None:
            row.is_admin = bool(is_admin_flag)


async def get_user_permissions(user_id: int) -> dict[str, Any]:
    profile = await ensure_user(user_id)
    return {
        "can_notify": bool(profile.get("can_notify")),
        "can_review": bool(profile.get("can_review")),
        "can_broadcast": bool(profile.get("can_broadcast")),
        "faculties": list(profile.get("faculties", [])),
        "groups": list(profile.get("groups", [])),
        "specialties": list(profile.get("specialties", profile.get("groups", []))),
        "is_admin": bool(profile.get("is_admin")),
    }


def _has_access(profile: dict[str, Any], key: str, value: str) -> bool:
    values = set(profile.get(key, []))
    return ALL_GROUPS in values or value in values


async def can_use_targeted_broadcast(user_id: int) -> bool:
    return bool(await is_admin(user_id) or (await get_user_permissions(user_id)).get("can_broadcast"))


async def can_notify(user_id: int, group: str, specialty: str | None = None) -> bool:
    profile = await ensure_user(user_id)
    if not profile.get("can_notify"):
        return False
    if specialty and _has_access(profile, "specialties", specialty):
        return True
    if specialty:
        faculty = faculty_by_specialty(specialty)
        if faculty and _has_access(profile, "faculties", faculty):
            return True
    return _has_access(profile, "groups", group)


async def can_review(user_id: int, group: str, specialty: str | None = None) -> bool:
    profile = await ensure_user(user_id)
    if not profile.get("can_review"):
        return False
    if specialty and _has_access(profile, "specialties", specialty):
        return True
    if specialty:
        faculty = faculty_by_specialty(specialty)
        if faculty and _has_access(profile, "faculties", faculty):
            return True
    return _has_access(profile, "groups", group)


async def get_notification_receivers(group: str, specialty: str | None = None) -> list[int]:
    async with session_scope() as session:
        await _seed_defaults_if_empty(session)
        rows = await repo.access_list_all(session)
    receivers: list[int] = []
    for user_id, profile in rows:
        if not profile.get("can_notify"):
            continue
        if specialty and _has_access(profile, "specialties", specialty):
            receivers.append(user_id)
            continue
        if specialty:
            faculty = faculty_by_specialty(specialty)
            if faculty and _has_access(profile, "faculties", faculty):
                receivers.append(user_id)
                continue
        if _has_access(profile, "groups", group):
            receivers.append(user_id)
    if not receivers:
        receivers = [int(settings.admin_id)]
    return sorted(set(receivers))


async def list_managers() -> list[tuple[int, dict[str, Any]]]:
    async with session_scope() as session:
        await _seed_defaults_if_empty(session)
        rows = await repo.access_list_all(session)
    return [
        (user_id, profile)
        for user_id, profile in rows
        if profile.get("can_notify") or profile.get("can_review") or profile.get("is_admin")
    ]


def get_all_specialties(lang: str = "ru", track: str | None = None) -> list[str]:
    if track in {"uni", "college"}:
        return sorted(set(catalog_get_all_specialties(lang, track)))
    merged = set(catalog_get_all_specialties(lang, "uni"))
    merged.update(catalog_get_all_specialties(lang, "college"))
    return sorted(merged)


def get_all_faculties(lang: str = "ru") -> list[str]:
    values: set[str] = set()
    for track_map in SPECIALTIES_BY_TRACK.values():
        values.update(track_map.get(lang, {}).keys())
    return sorted(values)


def faculty_by_specialty(specialty: str) -> str | None:
    needle = str(specialty).strip()
    if not needle:
        return None
    for track_map in SPECIALTIES_BY_TRACK.values():
        for departments in track_map.values():
            for faculty, specs in departments.items():
                if needle in specs:
                    return faculty
    return None
