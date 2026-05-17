"""Пакеты документов: async API поверх PostgreSQL."""

from __future__ import annotations

from typing import Any

from db.database import session_scope
from db import repositories as repo


async def add_pending_package(package: dict[str, Any]) -> None:
    async with session_scope() as session:
        await repo.document_add_pending(session, package)


async def get_pending_package(tg_user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.document_get(session, tg_user_id, status="pending")


async def mark_package_approved(tg_user_id: int, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.document_move_status(
            session,
            tg_user_id,
            new_status="approved",
            reviewer_id=reviewer_id,
            reviewer_username=reviewer_username,
        )


async def mark_package_denied(tg_user_id: int, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    async with session_scope() as session:
        return await repo.document_move_status(
            session,
            tg_user_id,
            new_status="denied",
            reviewer_id=reviewer_id,
            reviewer_username=reviewer_username,
        )


async def get_package_for_review(tg_user_id: int) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = await repo.document_get(session, tg_user_id)
        return row


async def get_any_package(tg_user_id: int) -> tuple[str, dict[str, Any]] | None:
    async with session_scope() as session:
        return await repo.document_get_any(session, tg_user_id)


async def get_pending_packages() -> dict[str, dict[str, Any]]:
    async with session_scope() as session:
        return await repo.document_pending_map(session)


async def list_packages_by_status(status: str) -> list[dict[str, Any]]:
    async with session_scope() as session:
        return await repo.document_list_by_status(session, status)


async def overwrite_pending_packages(items: dict[str, dict[str, Any]]) -> None:
    async with session_scope() as session:
        await repo.document_overwrite_pending(session, items)


async def delete_user_package_data(tg_user_id: int) -> bool:
    async with session_scope() as session:
        return await repo.document_delete_user(session, tg_user_id)
