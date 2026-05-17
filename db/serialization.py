"""Преобразование ORM <-> dict для совместимости с существующими handlers/services."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db.models import AccessProfile, DocumentPackage, Registration, StudyGroup, SupportTicket


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def registration_to_dict(row: Registration) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tg_user_id": int(row.tg_user_id),
        "phone": row.phone,
        "status": row.status,
        "fio": row.fio,
        "role": row.role,
        "faculty": row.faculty,
        "specialty": row.specialty,
        "course": row.course,
        "group": row.group,
        "admission_track": row.admission_track,
        "is_grant": bool(row.is_grant),
        "submit_attempt": int(row.submit_attempt),
        "responsible_id": row.responsible_id,
        "reviewed_by": row.reviewed_by,
        "reviewed_by_username": row.reviewed_by_username,
        "tg_username": row.tg_username,
        "created_at": _iso(row.created_at),
        "reviewed_at": _iso(row.reviewed_at),
        "profile_updated_at": _iso(row.profile_updated_at),
    }
    extra = dict(row.extra or {})
    for key, value in extra.items():
        if key not in data:
            data[key] = value
    return data


def registration_apply_dict(row: Registration, record: dict[str, Any]) -> None:
    """Заполняет ORM из входного dict (лишние ключи уходят в extra)."""
    known = {
        "tg_user_id",
        "phone",
        "status",
        "fio",
        "role",
        "faculty",
        "specialty",
        "course",
        "group",
        "admission_track",
        "is_grant",
        "submit_attempt",
        "responsible_id",
        "reviewed_by",
        "reviewed_by_username",
        "tg_username",
    }
    extra = dict(row.extra or {})
    for key, value in record.items():
        if key in known:
            setattr(row, key, value)
        elif key not in {"created_at", "reviewed_at", "profile_updated_at", "id"}:
            extra[key] = value
    row.extra = extra


def document_package_to_dict(row: DocumentPackage) -> dict[str, Any]:
    data = dict(row.payload or {})
    data.setdefault("tg_user_id", int(row.tg_user_id))
    data["submit_attempt"] = int(row.submit_attempt)
    data["created_at"] = _iso(row.created_at)
    data["review_status"] = row.review_status
    return data


def access_profile_to_dict(row: AccessProfile) -> dict[str, Any]:
    return {
        "can_notify": bool(row.can_notify),
        "can_review": bool(row.can_review),
        "can_broadcast": bool(row.can_broadcast),
        "is_admin": bool(row.is_admin),
        "faculties": list(row.faculties or []),
        "groups": list(row.groups or []),
        "specialties": list(row.specialties or []),
    }


def study_group_to_dict(row: StudyGroup) -> dict[str, str]:
    return {
        "track": row.track,
        "faculty": row.faculty,
        "specialty": row.specialty,
        "course": row.course,
        "group_name": row.group_name,
        "created_by": str(row.created_by),
    }


def support_ticket_to_dict(row: SupportTicket) -> dict[str, Any]:
    data = dict(row.payload or {})
    data["ticket_id"] = str(row.ticket_id)
    data["user_id"] = int(row.user_id)
    data["topic_code"] = row.topic_code
    data["status"] = row.status
    data["anonymous"] = bool(row.anonymous)
    return data


def support_ticket_from_payload(ticket_id: str, payload: dict[str, Any]) -> tuple[SupportTicket, dict[str, Any]]:
    body = dict(payload)
    user_id = int(body.pop("user_id", 0) or 0)
    topic_code = str(body.pop("topic_code", "psy"))
    status = str(body.pop("status", "open"))
    anonymous = bool(body.pop("anonymous", False))
    body.pop("ticket_id", None)
    row = SupportTicket(
        ticket_id=str(ticket_id),
        user_id=user_id,
        topic_code=topic_code,
        status=status,
        anonymous=anonymous,
        payload=body,
    )
    return row, body
