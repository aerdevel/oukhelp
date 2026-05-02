import json
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from utils.file_utils import read_json, write_json


STORE_PATH = Path("data/documents_review.json")


def _ensure_store() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        STORE_PATH.write_text(
            json.dumps({"pending": {}, "approved": {}, "denied": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _read_store() -> dict[str, dict[str, Any]]:
    _ensure_store()
    data = read_json(STORE_PATH, {"pending": {}, "approved": {}, "denied": {}})
    data.setdefault("pending", {})
    data.setdefault("approved", {})
    data.setdefault("denied", {})
    return data


def _write_store(data: dict[str, dict[str, Any]]) -> None:
    _ensure_store()
    write_json(STORE_PATH, data)


def _next_submit_attempt(data: dict[str, dict[str, Any]], tg_user_id: int) -> int:
    user_key = str(tg_user_id)
    current_max = 0
    for bucket in ("pending", "approved", "denied"):
        row = data.get(bucket, {}).get(user_key)
        if not row:
            continue
        attempt = int(row.get("submit_attempt", 0) or 0)
        current_max = max(current_max, attempt)
    return current_max + 1


def add_pending_package(package: dict[str, Any]) -> None:
    data = _read_store()
    package.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    user_key = str(package["tg_user_id"])
    package["submit_attempt"] = _next_submit_attempt(data, int(package["tg_user_id"]))
    data["pending"][user_key] = package
    _write_store(data)


def get_pending_package(tg_user_id: int) -> dict[str, Any] | None:
    data = _read_store()
    return data["pending"].get(str(tg_user_id))


def mark_package_approved(tg_user_id: int, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    data = _read_store()
    user_key = str(tg_user_id)
    package = data["pending"].pop(user_key, None)
    if not package:
        return None
    package["review_status"] = "approved"
    package["reviewer_id"] = reviewer_id
    package["reviewer_username"] = reviewer_username or ""
    data["approved"][user_key] = package
    _write_store(data)
    return package


def mark_package_denied(tg_user_id: int, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    data = _read_store()
    user_key = str(tg_user_id)
    package = data["pending"].pop(user_key, None)
    if not package:
        return None
    package["review_status"] = "denied"
    package["reviewer_id"] = reviewer_id
    package["reviewer_username"] = reviewer_username or ""
    data["denied"][user_key] = package
    _write_store(data)
    return package


def get_package_for_review(tg_user_id: int) -> dict[str, Any] | None:
    """Возвращает пакет из любого статуса, чтобы модераторы могли открыть документы повторно."""
    data = _read_store()
    user_key = str(tg_user_id)
    return data["pending"].get(user_key) or data["approved"].get(user_key) or data["denied"].get(user_key)


def get_any_package(tg_user_id: int) -> tuple[str, dict[str, Any]] | None:
    data = _read_store()
    user_key = str(tg_user_id)
    for bucket in ("pending", "approved", "denied"):
        row = data[bucket].get(user_key)
        if row:
            return bucket, row
    return None


def get_pending_packages() -> dict[str, dict[str, Any]]:
    return dict(_read_store().get("pending", {}))


def overwrite_pending_packages(items: dict[str, dict[str, Any]]) -> None:
    data = _read_store()
    data["pending"] = items
    _write_store(data)


def delete_user_package_data(tg_user_id: int) -> bool:
    data = _read_store()
    user_key = str(tg_user_id)
    changed = False
    for bucket in ("pending", "approved", "denied"):
        if user_key in data[bucket]:
            data[bucket].pop(user_key, None)
            changed = True
    if changed:
        _write_store(data)
    return changed
