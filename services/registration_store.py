"""Публичный API регистраций (async). Реализация — PostgreSQL через db.repositories."""

from __future__ import annotations

from typing import Any

from db.database import session_scope
from db import repositories as repo


async def add_pending_registration(record: dict[str, Any]) -> None:
    async with session_scope() as session:
        await repo.registration_add_pending(session, record)


async def get_pending_for_responsible(responsible_id: int) -> list[dict[str, Any]]:
    rows = await get_pending_all()
    return [item for item in rows if int(item.get("responsible_id", 0)) == int(responsible_id)]


async def get_pending_all() -> list[dict[str, Any]]:
    async with session_scope() as session:
        return await repo.registration_list_by_status(session, "pending")


async def get_pending_by_phone(phone: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_find_by_phone(session, phone, status="pending")


async def find_phone_owner(phone: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_find_phone_owner(session, phone)


async def approve_registration(phone: str, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_move_status(
            session,
            phone,
            new_status="approved",
            reviewer_id=reviewer_id,
            reviewer_username=reviewer_username,
        )


async def deny_registration(phone: str, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_move_status(
            session,
            phone,
            new_status="denied",
            reviewer_id=reviewer_id,
            reviewer_username=reviewer_username,
        )


async def get_approved_user(tg_user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_get_by_tg(session, tg_user_id, status="approved")


async def get_approved_all() -> list[dict[str, Any]]:
    async with session_scope() as session:
        return await repo.registration_list_by_status(session, "approved")


async def get_any_registration(tg_user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_get_any(session, tg_user_id)


async def get_pending_by_tg_user_id(tg_user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_get_by_tg(session, tg_user_id, status="pending")


async def get_processed_all() -> list[dict[str, Any]]:
    async with session_scope() as session:
        return await repo.registration_processed_all(session)


async def get_pending_registrations() -> list[dict[str, Any]]:
    return await get_pending_all()


async def overwrite_pending_registrations(items: list[dict[str, Any]]) -> None:
    async with session_scope() as session:
        await repo.registration_overwrite_pending(session, items)


async def delete_user_registration_data(tg_user_id: int) -> bool:
    async with session_scope() as session:
        return await repo.registration_delete_user(session, tg_user_id)


async def update_approved_profile(tg_user_id: int, **fields: Any) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_update_approved_fields(session, tg_user_id, **fields)


async def set_user_grant_flag(tg_user_id: int, is_grant: bool) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.registration_set_grant(session, tg_user_id, is_grant)
