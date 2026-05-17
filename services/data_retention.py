from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.documents_store import get_pending_packages, overwrite_pending_packages
from services.registration_store import get_pending_registrations, overwrite_pending_registrations
from utils.datetime_utils import parse_iso_utc


async def cleanup_stale_pending_data(retention_days: int) -> dict[str, int]:
    """
    Очищает устаревшие pending-данные.
    Удаляем только pending, чтобы не ломать историю принятых/отклоненных решений.
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed_registrations = 0
    removed_packages = 0

    pending_regs = await get_pending_registrations()
    filtered_regs = []
    for row in pending_regs:
        created_at = parse_iso_utc(str(row.get("created_at", "")))
        if created_at and created_at < threshold:
            removed_registrations += 1
            continue
        filtered_regs.append(row)
    if removed_registrations:
        await overwrite_pending_registrations(filtered_regs)

    pending_packages = await get_pending_packages()
    filtered_packages = {}
    for key, row in pending_packages.items():
        created_at = parse_iso_utc(str(row.get("created_at", "")))
        if created_at and created_at < threshold:
            removed_packages += 1
            continue
        filtered_packages[key] = row
    if removed_packages:
        await overwrite_pending_packages(filtered_packages)

    return {
        "removed_pending_registrations": removed_registrations,
        "removed_pending_packages": removed_packages,
    }
