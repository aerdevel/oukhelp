"""Репозитории: единственная точка SQL-доступа (handlers сюда не ходят)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AccessProfile,
    AuditEvent,
    DocumentPackage,
    Registration,
    SchemaMigrationFlag,
    StudyGroup,
    SupportMeta,
    SupportTicket,
)
from db.serialization import (
    access_profile_to_dict,
    document_package_to_dict,
    registration_apply_dict,
    registration_to_dict,
    study_group_to_dict,
    support_ticket_from_payload,
    support_ticket_to_dict,
)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Registrations ---


async def registration_next_submit_attempt(session: AsyncSession, tg_user_id: int) -> int:
    result = await session.execute(
        select(func.max(Registration.submit_attempt)).where(Registration.tg_user_id == tg_user_id)
    )
    current = result.scalar() or 0
    return int(current) + 1


async def registration_add_pending(session: AsyncSession, record: dict[str, Any]) -> None:
    tg_user_id = _safe_int(record.get("tg_user_id"))
    phone = str(record.get("phone", ""))
    await session.execute(
        delete(Registration).where(
            Registration.status == "pending",
            (Registration.phone == phone) | (Registration.tg_user_id == tg_user_id),
        )
    )
    row = Registration(
        tg_user_id=tg_user_id,
        phone=phone,
        status="pending",
        created_at=_utcnow(),
    )
    registration_apply_dict(row, record)
    row.status = "pending"
    if tg_user_id:
        row.submit_attempt = await registration_next_submit_attempt(session, tg_user_id)
    else:
        row.submit_attempt = _safe_int(record.get("submit_attempt"), 1) or 1
    session.add(row)


async def registration_list_by_status(session: AsyncSession, status: str) -> list[dict[str, Any]]:
    result = await session.execute(select(Registration).where(Registration.status == status))
    return [registration_to_dict(r) for r in result.scalars().all()]


async def registration_find_by_phone(session: AsyncSession, phone: str, *, status: str | None = None) -> dict[str, Any] | None:
    stmt = select(Registration).where(Registration.phone == phone)
    if status:
        stmt = stmt.where(Registration.status == status)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return registration_to_dict(row) if row else None


async def registration_find_phone_owner(session: AsyncSession, phone: str) -> dict[str, Any] | None:
    for st in ("approved", "pending", "denied"):
        row = await registration_find_by_phone(session, phone, status=st)
        if row:
            row["_bucket"] = st
            return row
    return None


async def registration_get_by_tg(session: AsyncSession, tg_user_id: int, *, status: str | None = None) -> dict[str, Any] | None:
    stmt = select(Registration).where(Registration.tg_user_id == tg_user_id)
    if status:
        stmt = stmt.where(Registration.status == status)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return registration_to_dict(row) if row else None


async def registration_get_any(session: AsyncSession, tg_user_id: int) -> dict[str, Any] | None:
    result = await session.execute(
        select(Registration).where(Registration.tg_user_id == tg_user_id).limit(1)
    )
    row = result.scalar_one_or_none()
    return registration_to_dict(row) if row else None


async def registration_move_status(
    session: AsyncSession,
    phone: str,
    *,
    new_status: str,
    reviewer_id: int,
    reviewer_username: str | None,
) -> dict[str, Any] | None:
    result = await session.execute(
        select(Registration).where(Registration.phone == phone, Registration.status == "pending")
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    tg_user_id = int(row.tg_user_id)
    await session.execute(delete(Registration).where(Registration.tg_user_id == tg_user_id, Registration.status != "pending"))
    row.status = new_status
    row.reviewed_by = reviewer_id
    row.reviewed_by_username = reviewer_username or ""
    row.reviewed_at = _utcnow()
    session.add(row)
    return registration_to_dict(row)


async def registration_update_approved_fields(session: AsyncSession, tg_user_id: int, **fields: Any) -> dict[str, Any] | None:
    result = await session.execute(
        select(Registration).where(Registration.tg_user_id == tg_user_id, Registration.status == "approved")
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    patch = {k: v for k, v in fields.items() if v is not None}
    registration_apply_dict(row, patch)
    row.profile_updated_at = _utcnow()
    return registration_to_dict(row)


async def registration_set_grant(session: AsyncSession, tg_user_id: int, is_grant: bool) -> dict[str, Any] | None:
    result = await session.execute(select(Registration).where(Registration.tg_user_id == tg_user_id))
    rows = result.scalars().all()
    if not rows:
        return None
    updated: Registration | None = None
    for row in rows:
        row.is_grant = bool(is_grant)
        updated = row
    return registration_to_dict(updated) if updated else None


async def registration_delete_user(session: AsyncSession, tg_user_id: int) -> bool:
    result = await session.execute(delete(Registration).where(Registration.tg_user_id == tg_user_id))
    return bool(result.rowcount)


async def registration_overwrite_pending(session: AsyncSession, items: list[dict[str, Any]]) -> None:
    await session.execute(delete(Registration).where(Registration.status == "pending"))
    for record in items:
        row = Registration(tg_user_id=_safe_int(record.get("tg_user_id")), phone=str(record.get("phone", "")), status="pending")
        registration_apply_dict(row, record)
        row.status = "pending"
        session.add(row)


async def registration_processed_all(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(select(Registration).where(Registration.status.in_(("approved", "denied"))))
    rows = [registration_to_dict(r) for r in result.scalars().all()]
    return sorted(rows, key=lambda row: str(row.get("reviewed_at", "")), reverse=True)


# --- Document packages ---


async def document_next_submit_attempt(session: AsyncSession, tg_user_id: int) -> int:
    result = await session.execute(
        select(func.max(DocumentPackage.submit_attempt)).where(DocumentPackage.tg_user_id == tg_user_id)
    )
    return int(result.scalar() or 0) + 1


async def document_add_pending(session: AsyncSession, package: dict[str, Any]) -> None:
    tg_user_id = _safe_int(package["tg_user_id"])
    attempt = await document_next_submit_attempt(session, tg_user_id)
    body = dict(package)
    body["submit_attempt"] = attempt
    row = DocumentPackage(
        tg_user_id=tg_user_id,
        review_status="pending",
        submit_attempt=attempt,
        created_at=_utcnow(),
        payload=body,
    )
    await session.merge(row)


async def document_get(session: AsyncSession, tg_user_id: int, *, status: str | None = None) -> dict[str, Any] | None:
    stmt = select(DocumentPackage).where(DocumentPackage.tg_user_id == tg_user_id)
    if status:
        stmt = stmt.where(DocumentPackage.review_status == status)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return document_package_to_dict(row) if row else None


async def document_get_any(session: AsyncSession, tg_user_id: int) -> tuple[str, dict[str, Any]] | None:
    result = await session.execute(select(DocumentPackage).where(DocumentPackage.tg_user_id == tg_user_id))
    row = result.scalar_one_or_none()
    if not row:
        return None
    return row.review_status, document_package_to_dict(row)


async def document_move_status(
    session: AsyncSession,
    tg_user_id: int,
    *,
    new_status: str,
    reviewer_id: int,
    reviewer_username: str | None,
) -> dict[str, Any] | None:
    result = await session.execute(
        select(DocumentPackage).where(
            DocumentPackage.tg_user_id == tg_user_id,
            DocumentPackage.review_status == "pending",
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    payload = document_package_to_dict(row)
    payload["review_status"] = new_status
    payload["reviewer_id"] = reviewer_id
    payload["reviewer_username"] = reviewer_username or ""
    row.review_status = new_status
    row.payload = payload
    return payload


async def document_delete_user(session: AsyncSession, tg_user_id: int) -> bool:
    result = await session.execute(delete(DocumentPackage).where(DocumentPackage.tg_user_id == tg_user_id))
    return bool(result.rowcount)


async def document_list_by_status(session: AsyncSession, status: str) -> list[dict[str, Any]]:
    result = await session.execute(select(DocumentPackage).where(DocumentPackage.review_status == status))
    return [document_package_to_dict(r) for r in result.scalars().all()]


async def document_pending_map(session: AsyncSession) -> dict[str, dict[str, Any]]:
    result = await session.execute(select(DocumentPackage).where(DocumentPackage.review_status == "pending"))
    return {str(r.tg_user_id): document_package_to_dict(r) for r in result.scalars().all()}


async def document_overwrite_pending(session: AsyncSession, items: dict[str, dict[str, Any]]) -> None:
    await session.execute(delete(DocumentPackage).where(DocumentPackage.review_status == "pending"))
    for key, package in items.items():
        tg_user_id = _safe_int(package.get("tg_user_id", key))
        row = DocumentPackage(
            tg_user_id=tg_user_id,
            review_status="pending",
            submit_attempt=_safe_int(package.get("submit_attempt"), 1),
            created_at=_utcnow(),
            payload=dict(package),
        )
        session.add(row)


# --- Access control ---


async def access_get(session: AsyncSession, user_id: int) -> AccessProfile | None:
    return await session.get(AccessProfile, user_id)


async def access_ensure(session: AsyncSession, user_id: int) -> AccessProfile:
    row = await access_get(session, user_id)
    if row is None:
        row = AccessProfile(user_id=user_id)
        session.add(row)
        await session.flush()
    return row


async def access_list_all(session: AsyncSession) -> list[tuple[int, dict[str, Any]]]:
    result = await session.execute(select(AccessProfile))
    return [(int(r.user_id), access_profile_to_dict(r)) for r in result.scalars().all()]


# --- Study groups ---


async def study_group_add(session: AsyncSession, *, track: str, faculty: str, specialty: str, course: str, group_name: str, created_by: int) -> bool:
    normalized = {
        "track": track.strip().lower(),
        "faculty": faculty.strip(),
        "specialty": specialty.strip(),
        "course": course.strip(),
        "group_name": group_name.strip(),
    }
    if not all(normalized.values()):
        return False
    exists = await session.execute(
        select(StudyGroup.id).where(
            StudyGroup.track == normalized["track"],
            StudyGroup.faculty == normalized["faculty"],
            StudyGroup.specialty == normalized["specialty"],
            StudyGroup.course == normalized["course"],
            StudyGroup.group_name == normalized["group_name"],
        )
    )
    if exists.scalar_one_or_none():
        return False
    session.add(StudyGroup(created_by=created_by, **normalized))
    return True


async def study_group_list(session: AsyncSession) -> list[dict[str, str]]:
    result = await session.execute(select(StudyGroup))
    return [study_group_to_dict(r) for r in result.scalars().all()]


# --- Support ---


async def support_meta_get(session: AsyncSession) -> SupportMeta:
    row = await session.get(SupportMeta, 1)
    if row is None:
        row = SupportMeta(id=1)
        session.add(row)
        await session.flush()
    return row


async def support_ticket_get(session: AsyncSession, ticket_id: str) -> dict[str, Any] | None:
    row = await session.get(SupportTicket, str(ticket_id))
    if row:
        return support_ticket_to_dict(row)
    digits = "".join(ch for ch in str(ticket_id) if ch.isdigit())
    if not digits:
        return None
    result = await session.execute(select(SupportTicket))
    for candidate in result.scalars().all():
        if candidate.ticket_id == digits:
            return support_ticket_to_dict(candidate)
        tid = "".join(ch for ch in str((candidate.payload or {}).get("ticket_id", "")) if ch.isdigit())
        if tid == digits:
            return support_ticket_to_dict(candidate)
    return None


async def support_ticket_save(session: AsyncSession, ticket: dict[str, Any]) -> None:
    ticket_id = str(ticket.get("ticket_id"))
    row, _ = support_ticket_from_payload(ticket_id, ticket)
    existing = await session.get(SupportTicket, ticket_id)
    if existing:
        existing.user_id = row.user_id
        existing.topic_code = row.topic_code
        existing.status = row.status
        existing.anonymous = row.anonymous
        existing.payload = row.payload
    else:
        session.add(row)


async def support_ticket_all(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(select(SupportTicket))
    return [support_ticket_to_dict(r) for r in result.scalars().all()]


async def support_ticket_delete(session: AsyncSession, ticket_id: str) -> None:
    await session.execute(delete(SupportTicket).where(SupportTicket.ticket_id == str(ticket_id)))


# --- Audit ---


async def audit_append(session: AsyncSession, event_type: str, actor_id: int, payload: dict[str, Any]) -> None:
    session.add(AuditEvent(event_type=event_type, actor_id=int(actor_id), payload=payload))


# --- Migration flag ---


async def migration_flag_get(session: AsyncSession, key: str) -> bool:
    return await session.get(SchemaMigrationFlag, key) is not None


async def migration_flag_set(session: AsyncSession, key: str) -> None:
    session.add(SchemaMigrationFlag(key=key))
