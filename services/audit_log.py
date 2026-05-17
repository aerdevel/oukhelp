"""Журнал действий админов/модераторов (PostgreSQL)."""

from __future__ import annotations

from typing import Any

from db.database import session_scope
from db import repositories as repo


async def append_audit_event(event_type: str, actor_id: int, payload: dict[str, Any]) -> None:
    async with session_scope() as session:
        await repo.audit_append(session, event_type, actor_id, payload)
