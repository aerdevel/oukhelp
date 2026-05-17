"""Справочник учебных групп (PostgreSQL)."""

from __future__ import annotations

from db.database import session_scope
from db import repositories as repo


async def add_group(*, track: str, faculty: str, specialty: str, course: str, group_name: str, created_by: int) -> bool:
    async with session_scope() as session:
        return await repo.study_group_add(
            session,
            track=track,
            faculty=faculty,
            specialty=specialty,
            course=course,
            group_name=group_name,
            created_by=created_by,
        )


async def _all_rows() -> list[dict[str, str]]:
    async with session_scope() as session:
        return await repo.study_group_list(session)


async def list_groups(*, track: str, specialty: str, course: str) -> list[str]:
    rows = await _all_rows()
    values = {
        row["group_name"]
        for row in rows
        if row["track"].lower() == track.lower() and row["specialty"] == specialty and row["course"] == course
    }
    return sorted(v for v in values if v)


async def list_all_groups(*, track: str) -> list[str]:
    rows = await _all_rows()
    values = {row["group_name"] for row in rows if row["track"].lower() == track.lower()}
    return sorted(v for v in values if v)


async def list_groups_detailed(*, track: str, faculty: str, specialty: str, course: str) -> list[dict[str, str]]:
    rows = await _all_rows()
    out: list[dict[str, str]] = []
    for row in rows:
        if (
            row["track"].lower() == track.lower()
            and row["faculty"] == faculty
            and row["specialty"] == specialty
            and row["course"] == course
            and row["group_name"]
        ):
            out.append(row)
    out.sort(key=lambda item: item["group_name"].lower())
    return out


async def update_group_name(
    *,
    track: str,
    faculty: str,
    specialty: str,
    course: str,
    old_group_name: str,
    new_group_name: str,
) -> bool:
    from sqlalchemy import delete, select

    from db.models import StudyGroup

    needle_old = old_group_name.strip()
    needle_new = new_group_name.strip()
    if not needle_old or not needle_new:
        return False
    async with session_scope() as session:
        conflict = await session.execute(
            select(StudyGroup.id).where(
                StudyGroup.track == track.lower(),
                StudyGroup.specialty == specialty,
                StudyGroup.course == course,
                StudyGroup.group_name == needle_new,
            )
        )
        if conflict.scalar_one_or_none():
            # разрешаем, если это переименование той же строки
            same = await session.execute(
                select(StudyGroup.id).where(
                    StudyGroup.track == track.lower(),
                    StudyGroup.faculty == faculty,
                    StudyGroup.specialty == specialty,
                    StudyGroup.course == course,
                    StudyGroup.group_name == needle_old,
                )
            )
            if not same.scalar_one_or_none():
                return False
        result = await session.execute(
            select(StudyGroup).where(
                StudyGroup.track == track.lower(),
                StudyGroup.faculty == faculty,
                StudyGroup.specialty == specialty,
                StudyGroup.course == course,
                StudyGroup.group_name == needle_old,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        row.group_name = needle_new
        return True


async def delete_group(*, track: str, faculty: str, specialty: str, course: str, group_name: str) -> bool:
    from sqlalchemy import delete

    from db.models import StudyGroup

    needle = group_name.strip()
    async with session_scope() as session:
        result = await session.execute(
            delete(StudyGroup).where(
                StudyGroup.track == track.lower(),
                StudyGroup.faculty == faculty,
                StudyGroup.specialty == specialty,
                StudyGroup.course == course,
                StudyGroup.group_name == needle,
            )
        )
        return bool(result.rowcount)


async def list_groups_for_specialties(*, track: str, specialties: list[str]) -> list[str]:
    allowed = {s.strip() for s in specialties if s.strip()}
    if not allowed:
        return []
    rows = await _all_rows()
    values = {
        row["group_name"]
        for row in rows
        if row["track"].lower() == track.lower() and row["specialty"] in allowed
    }
    return sorted(v for v in values if v)
