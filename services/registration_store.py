import json
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from utils.file_utils import read_json, write_json


STORE_PATH = Path("data/registrations.json")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_store() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        STORE_PATH.write_text(
            json.dumps({"pending": [], "approved": [], "denied": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _read_store() -> dict[str, list[dict[str, Any]]]:
    _ensure_store()
    data = read_json(STORE_PATH, {"pending": [], "approved": [], "denied": []})
    data.setdefault("pending", [])
    data.setdefault("approved", [])
    data.setdefault("denied", [])
    return data


def _write_store(data: dict[str, list[dict[str, Any]]]) -> None:
    _ensure_store()
    write_json(STORE_PATH, data)


def _next_submit_attempt(data: dict[str, list[dict[str, Any]]], tg_user_id: int) -> int:
    current_max = 0
    for bucket in ("pending", "approved", "denied"):
        for item in data.get(bucket, []):
            if _safe_int(item.get("tg_user_id"), 0) != _safe_int(tg_user_id, 0):
                continue
            attempt = _safe_int(item.get("submit_attempt"), 0)
            current_max = max(current_max, attempt)
    return current_max + 1


def add_pending_registration(record: dict[str, Any]) -> None:
    data = _read_store()
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    record["status"] = "pending"
    tg_user_id = _safe_int(record.get("tg_user_id"), 0)
    if tg_user_id:
        record["submit_attempt"] = _next_submit_attempt(data, tg_user_id)
    else:
        record["submit_attempt"] = int(record.get("submit_attempt", 0) or 0) or 1
    phone = str(record.get("phone", ""))
    data["pending"] = [
        item
        for item in data["pending"]
        if item.get("phone") != phone and item.get("tg_user_id") != tg_user_id
    ]
    data["pending"].append(record)
    _write_store(data)


def get_pending_for_responsible(responsible_id: int) -> list[dict[str, Any]]:
    data = _read_store()
    return [item for item in data["pending"] if int(item.get("responsible_id", 0)) == int(responsible_id)]


def get_pending_all() -> list[dict[str, Any]]:
    data = _read_store()
    return list(data["pending"])


def get_pending_by_phone(phone: str) -> dict[str, Any] | None:
    data = _read_store()
    for item in data["pending"]:
        if item.get("phone") == phone:
            return item
    return None


def find_phone_owner(phone: str) -> dict[str, Any] | None:
    data = _read_store()
    for bucket in ("approved", "pending", "denied"):
        for item in data[bucket]:
            if str(item.get("phone", "")) == str(phone):
                result = dict(item)
                result["_bucket"] = bucket
                return result
    return None


def approve_registration(phone: str, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    data = _read_store()
    picked = None
    pending = []
    for item in data["pending"]:
        if item.get("phone") == phone and picked is None:
            picked = item
            continue
        pending.append(item)
    if picked is None:
        return None
    picked["status"] = "approved"
    picked["reviewed_by"] = reviewer_id
    picked["reviewed_by_username"] = reviewer_username or ""
    picked["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    data["pending"] = pending
    data["approved"] = [item for item in data["approved"] if item.get("tg_user_id") != picked.get("tg_user_id")]
    data["denied"] = [item for item in data["denied"] if item.get("tg_user_id") != picked.get("tg_user_id")]
    data["approved"].append(picked)
    _write_store(data)
    return picked


def deny_registration(phone: str, reviewer_id: int, reviewer_username: str | None = None) -> dict[str, Any] | None:
    data = _read_store()
    picked = None
    pending = []
    for item in data["pending"]:
        if item.get("phone") == phone and picked is None:
            picked = item
            continue
        pending.append(item)
    if picked is None:
        return None
    picked["status"] = "denied"
    picked["reviewed_by"] = reviewer_id
    picked["reviewed_by_username"] = reviewer_username or ""
    picked["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    data["pending"] = pending
    data["approved"] = [item for item in data["approved"] if item.get("tg_user_id") != picked.get("tg_user_id")]
    data["denied"] = [item for item in data["denied"] if item.get("tg_user_id") != picked.get("tg_user_id")]
    data["denied"].append(picked)
    _write_store(data)
    return picked


def get_approved_user(tg_user_id: int) -> dict[str, Any] | None:
    data = _read_store()
    for item in data["approved"]:
        if _safe_int(item.get("tg_user_id"), 0) == _safe_int(tg_user_id, 0):
            return item
    return None


def get_approved_all() -> list[dict[str, Any]]:
    data = _read_store()
    return list(data["approved"])


def get_any_registration(tg_user_id: int) -> dict[str, Any] | None:
    data = _read_store()
    for bucket in ("pending", "approved", "denied"):
        for item in data[bucket]:
            if _safe_int(item.get("tg_user_id"), 0) == _safe_int(tg_user_id, 0):
                return item
    return None


def get_pending_by_tg_user_id(tg_user_id: int) -> dict[str, Any] | None:
    data = _read_store()
    for item in data["pending"]:
        if _safe_int(item.get("tg_user_id"), 0) == _safe_int(tg_user_id, 0):
            return item
    return None


def get_processed_all() -> list[dict[str, Any]]:
    data = _read_store()
    rows = list(data.get("approved", [])) + list(data.get("denied", []))
    return sorted(rows, key=lambda row: str(row.get("reviewed_at", "")), reverse=True)


def get_pending_registrations() -> list[dict[str, Any]]:
    return list(_read_store().get("pending", []))


def overwrite_pending_registrations(items: list[dict[str, Any]]) -> None:
    data = _read_store()
    data["pending"] = items
    _write_store(data)


def delete_user_registration_data(tg_user_id: int) -> bool:
    data = _read_store()
    before_pending = len(data["pending"])
    before_approved = len(data["approved"])
    before_denied = len(data["denied"])
    target_id = _safe_int(tg_user_id, 0)
    data["pending"] = [item for item in data["pending"] if _safe_int(item.get("tg_user_id"), 0) != target_id]
    data["approved"] = [item for item in data["approved"] if _safe_int(item.get("tg_user_id"), 0) != target_id]
    data["denied"] = [item for item in data["denied"] if _safe_int(item.get("tg_user_id"), 0) != target_id]
    changed = (
        len(data["pending"]) != before_pending
        or len(data["approved"]) != before_approved
        or len(data["denied"]) != before_denied
    )
    if changed:
        _write_store(data)
    return changed
