"""Слой хранения тикетов поддержки в PostgreSQL (совместим с прежним dict-форматом)."""

from __future__ import annotations

from typing import Any

from db.database import session_scope
from db import repositories as repo
from db.models import SupportMeta


async def load_bundle() -> dict[str, Any]:
    async with session_scope() as session:
        meta = await repo.support_meta_get(session)
        tickets_list = await repo.support_ticket_all(session)
        return {
            "seq_ticket": int(meta.seq_ticket),
            "user_aliases": dict(meta.user_aliases or {}),
            "message_links": dict(meta.message_links or {}),
            "blocked_actors": dict(meta.blocked_actors or {}),
            "staff_registry": dict(meta.staff_registry or {}),
            "tickets": {str(t["ticket_id"]): t for t in tickets_list},
        }


async def save_bundle(data: dict[str, Any]) -> None:
    async with session_scope() as session:
        meta = await repo.support_meta_get(session)
        meta.seq_ticket = int(data.get("seq_ticket", meta.seq_ticket))
        meta.user_aliases = dict(data.get("user_aliases", {}))
        meta.message_links = dict(data.get("message_links", {}))
        meta.blocked_actors = dict(data.get("blocked_actors", {}))
        meta.staff_registry = dict(data.get("staff_registry", {}))
        for ticket in (data.get("tickets") or {}).values():
            await repo.support_ticket_save(session, ticket)
