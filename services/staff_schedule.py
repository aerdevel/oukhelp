"""Расписание: фото на неделю по группе (одна актуальная запись на трек+группу)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.database import session_scope
from db.models import GroupSchedulePhoto
from services.access_control import can_review, get_user_permissions, is_admin
from services.cabinet import teaching_groups_from_profile
from services.registration_store import get_approved_all, get_approved_user


async def visible_groups_for_staff(actor_id: int) -> list[str]:
    profile = await get_approved_user(actor_id)
    groups: set[str] = set(teaching_groups_from_profile(profile or {}))
    perms = await get_user_permissions(actor_id)
    for name in perms.get("groups") or []:
        if name and name not in {"*", "-"}:
            groups.add(str(name).strip())

    rows = await get_approved_all()
    if await is_admin(actor_id):
        for row in rows:
            name = str(row.get("group", "")).strip()
            if name and name != "-":
                groups.add(name)
            for g in teaching_groups_from_profile(row):
                groups.add(g)
        return sorted(groups)

    for row in rows:
        group = str(row.get("group", "-"))
        if await can_review(actor_id, group, row.get("specialty")):
            name = group.strip()
            if name and name != "-":
                groups.add(name)
    return sorted(groups)


async def upsert_schedule_photo(
    *,
    created_by: int,
    admission_track: str,
    group_name: str,
    photo_file_id: str,
    photo_kind: str = "photo",
) -> dict[str, Any]:
    track = str(admission_track or "uni")
    group = str(group_name).strip()
    file_id = str(photo_file_id).strip()
    if not group or not file_id:
        raise ValueError("group_name and photo_file_id are required")

    async with session_scope() as session:
        stmt = (
            insert(GroupSchedulePhoto)
            .values(
                created_by=int(created_by),
                admission_track=track,
                group_name=group,
                photo_file_id=file_id,
                photo_kind=str(photo_kind or "photo"),
            )
            .on_conflict_do_update(
                constraint="uq_schedule_photo_group_track",
                set_={
                    "created_by": int(created_by),
                    "photo_file_id": file_id,
                    "photo_kind": str(photo_kind or "photo"),
                },
            )
            .returning(GroupSchedulePhoto)
        )
        result = await session.execute(stmt)
        row = result.scalar_one()
        return _photo_to_dict(row)


async def get_schedule_photo(group_name: str, *, track: str | None = None) -> dict[str, Any] | None:
    group = str(group_name).strip()
    if not group:
        return None
    async with session_scope() as session:
        stmt = select(GroupSchedulePhoto).where(GroupSchedulePhoto.group_name == group)
        if track in {"uni", "college"}:
            stmt = stmt.where(GroupSchedulePhoto.admission_track == track)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return _photo_to_dict(row) if row else None


async def list_schedule_photos_for_groups(groups: list[str], *, track: str | None = None) -> list[dict[str, Any]]:
    if not groups:
        return []
    async with session_scope() as session:
        stmt = select(GroupSchedulePhoto).where(GroupSchedulePhoto.group_name.in_(groups))
        if track in {"uni", "college"}:
            stmt = stmt.where(GroupSchedulePhoto.admission_track == track)
        stmt = stmt.order_by(GroupSchedulePhoto.group_name)
        result = await session.execute(stmt)
        return [_photo_to_dict(row) for row in result.scalars().all()]


def _photo_to_dict(row: GroupSchedulePhoto) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "created_by": int(row.created_by),
        "admission_track": row.admission_track,
        "group_name": row.group_name,
        "photo_file_id": row.photo_file_id,
        "photo_kind": row.photo_kind or "photo",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
