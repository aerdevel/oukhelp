import json
from pathlib import Path
from typing import Any

from core.config import settings
from core.resources.text_file.catalog import SPECIALTIES_BY_DEPARTMENT
from utils.file_utils import read_json, write_json


STORE_PATH = Path("data/access_control.json")
ALL_GROUPS = "*"


def _default_payload() -> dict[str, Any]:
    # Базовые права: только админ и приемная комиссия.
    users = {
        str(int(settings.admin_id)): {
            "can_notify": True,
            "can_review": True,
            "groups": [ALL_GROUPS],
            "specialties": [ALL_GROUPS],
            "is_admin": True,
        },
        str(int(settings.priemka_id)): {
            "can_notify": True,
            "can_review": True,
            "groups": [ALL_GROUPS],
            "specialties": [ALL_GROUPS],
            "is_admin": False,
        },
    }
    return {"users": users}


def _ensure_store() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        STORE_PATH.write_text(json.dumps(_default_payload(), ensure_ascii=False, indent=2), encoding="utf-8")


def _read_store() -> dict[str, Any]:
    _ensure_store()
    data = read_json(STORE_PATH, _default_payload())
    data.setdefault("users", {})
    # Мягкая миграция старого формата без specialties.
    for profile in data["users"].values():
        profile.setdefault("can_notify", False)
        profile.setdefault("can_review", False)
        profile.setdefault("groups", [])
        profile.setdefault("specialties", list(profile.get("groups", [])))
        profile.setdefault("is_admin", False)
    return data


def _write_store(data: dict[str, Any]) -> None:
    _ensure_store()
    write_json(STORE_PATH, data)


def is_admin(user_id: int) -> bool:
    if int(user_id) == int(settings.admin_id):
        return True
    data = _read_store()
    profile = data["users"].get(str(user_id), {})
    return bool(profile.get("is_admin", False))


def ensure_user(user_id: int) -> dict[str, Any]:
    data = _read_store()
    users = data["users"]
    profile = users.get(str(user_id))
    if profile is None:
        profile = {"can_notify": False, "can_review": False, "groups": [], "specialties": [], "is_admin": False}
        users[str(user_id)] = profile
        _write_store(data)
    return profile


def set_user_permissions(
    actor_id: int,
    target_user_id: int,
    *,
    can_notify: bool | None = None,
    can_review: bool | None = None,
    groups: list[str] | None = None,
    specialties: list[str] | None = None,
    is_admin_flag: bool | None = None,
) -> None:
    if not is_admin(actor_id):
        raise PermissionError("Недостаточно прав для изменения доступов.")
    data = _read_store()
    profile = data["users"].get(
        str(target_user_id),
        {"can_notify": False, "can_review": False, "groups": [], "specialties": [], "is_admin": False},
    )
    if can_notify is not None:
        profile["can_notify"] = bool(can_notify)
    if can_review is not None:
        profile["can_review"] = bool(can_review)
    if groups is not None:
        normalized = [grp.strip() for grp in groups if grp.strip()]
        profile["groups"] = normalized
    if specialties is not None:
        normalized = [spec.strip() for spec in specialties if spec.strip()]
        profile["specialties"] = normalized
    if is_admin_flag is not None:
        profile["is_admin"] = bool(is_admin_flag)
    data["users"][str(target_user_id)] = profile
    _write_store(data)


def get_user_permissions(user_id: int) -> dict[str, Any]:
    profile = ensure_user(user_id)
    return {
        "can_notify": bool(profile.get("can_notify")),
        "can_review": bool(profile.get("can_review")),
        "groups": list(profile.get("groups", [])),
        "specialties": list(profile.get("specialties", profile.get("groups", []))),
        "is_admin": bool(profile.get("is_admin")),
    }


def _has_access(profile: dict[str, Any], key: str, value: str) -> bool:
    values = set(profile.get(key, []))
    return ALL_GROUPS in values or value in values


def can_notify(user_id: int, group: str, specialty: str | None = None) -> bool:
    profile = ensure_user(user_id)
    if not profile.get("can_notify"):
        return False
    # Новый контур: сначала фильтрация по специальности, затем fallback по группе.
    if specialty and _has_access(profile, "specialties", specialty):
        return True
    return _has_access(profile, "groups", group)


def can_review(user_id: int, group: str, specialty: str | None = None) -> bool:
    profile = ensure_user(user_id)
    if not profile.get("can_review"):
        return False
    if specialty and _has_access(profile, "specialties", specialty):
        return True
    return _has_access(profile, "groups", group)


def get_notification_receivers(group: str, specialty: str | None = None) -> list[int]:
    data = _read_store()
    receivers: list[int] = []
    for raw_user_id, profile in data["users"].items():
        if not profile.get("can_notify"):
            continue
        if specialty and _has_access(profile, "specialties", specialty):
            receivers.append(int(raw_user_id))
            continue
        if _has_access(profile, "groups", group):
            receivers.append(int(raw_user_id))
    if not receivers:
        receivers = [int(settings.admin_id)]
    return sorted(set(receivers))


def list_managers() -> list[tuple[int, dict[str, Any]]]:
    data = _read_store()
    items: list[tuple[int, dict[str, Any]]] = []
    for raw_user_id, profile in data["users"].items():
        if profile.get("can_notify") or profile.get("can_review") or profile.get("is_admin"):
            items.append((int(raw_user_id), profile))
    return sorted(items, key=lambda row: row[0])


def get_all_specialties(lang: str = "ru") -> list[str]:
    departments = SPECIALTIES_BY_DEPARTMENT.get(lang, {})
    return [spec for specs in departments.values() for spec in specs]
