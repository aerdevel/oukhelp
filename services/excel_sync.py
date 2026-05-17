"""Синхронизация Excel-реестров с актуальным состоянием PostgreSQL."""

from __future__ import annotations

import logging
from typing import Any

from services.documents_store import list_packages_by_status
from services.excel_registry import (
    rebuild_accounts_registry,
    rebuild_applicants_registry,
    rebuild_staff_registry,
)
from services.registration_store import get_approved_all

_TRACKS = ("uni", "college")


async def sync_all_excel_from_database() -> dict[str, Any]:
    """
    Пересобирает все шесть реестров из БД.
    Удалённые из БД пользователи исчезают из Excel.
    """
    approved_regs = await get_approved_all()
    approved_packages = await list_packages_by_status("approved")

    stats: dict[str, Any] = {
        "approved_registrations": len(approved_regs),
        "approved_packages": len(approved_packages),
        "files": {},
    }

    for track in _TRACKS:
        stats["files"][f"accounts_{track}"] = rebuild_accounts_registry(approved_regs, track=track)
        stats["files"][f"staff_{track}"] = rebuild_staff_registry(approved_regs, track=track)
        stats["files"][f"applicants_{track}"] = rebuild_applicants_registry(approved_packages, track=track)

    logging.info(
        "Excel sync: regs=%s packages=%s paths=%s",
        stats["approved_registrations"],
        stats["approved_packages"],
        {k: v.get("path") for k, v in stats["files"].items()},
    )
    return stats
