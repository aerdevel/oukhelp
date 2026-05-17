"""Однократный импорт legacy JSON-файлов в PostgreSQL при первом запуске."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from db.database import session_scope
from db.models import (
    AccessProfile,
    DocumentPackage,
    Registration,
    SchemaMigrationFlag,
    StudyGroup,
    SupportMeta,
    SupportTicket,
)
from db.repositories import migration_flag_get, migration_flag_set
from db.serialization import registration_apply_dict, support_ticket_from_payload
from utils.file_utils import read_json

IMPORT_FLAG = "legacy_json_v1"

_LEGACY_FILES = {
    "registrations": Path("data/registrations.json"),
    "documents": Path("data/documents_review.json"),
    "access": Path("data/access_control.json"),
    "study_groups": Path("data/study_groups.json"),
    "support": Path("data/support_tickets.json"),
}


async def import_legacy_json_if_needed() -> None:
    async with session_scope() as session:
        if await migration_flag_get(session, IMPORT_FLAG):
            return
        reg_count = await session.scalar(select(func.count()).select_from(Registration))
        if reg_count and reg_count > 0:
            await migration_flag_set(session, IMPORT_FLAG)
            logging.info("PostgreSQL уже содержит данные, импорт JSON пропущен")
            return

    logging.info("Импорт legacy JSON в PostgreSQL...")
    await _import_registrations()
    await _import_documents()
    await _import_access()
    await _import_study_groups()
    await _import_support()

    async with session_scope() as session:
        await migration_flag_set(session, IMPORT_FLAG)
    logging.info("Импорт legacy JSON завершён")


async def _import_registrations() -> None:
    path = _LEGACY_FILES["registrations"]
    if not path.exists():
        return
    data = read_json(path, {"pending": [], "approved": [], "denied": []})
    async with session_scope() as session:
        for bucket in ("pending", "approved", "denied"):
            for record in data.get(bucket, []):
                row = Registration(
                    tg_user_id=int(record.get("tg_user_id", 0) or 0),
                    phone=str(record.get("phone", "")),
                    status=bucket,
                )
                registration_apply_dict(row, record)
                row.status = bucket
                session.add(row)


async def _import_documents() -> None:
    path = _LEGACY_FILES["documents"]
    if not path.exists():
        return
    data = read_json(path, {"pending": {}, "approved": {}, "denied": {}})
    async with session_scope() as session:
        for bucket in ("pending", "approved", "denied"):
            for key, package in (data.get(bucket) or {}).items():
                tg_user_id = int(package.get("tg_user_id", key) or 0)
                session.add(
                    DocumentPackage(
                        tg_user_id=tg_user_id,
                        review_status=bucket,
                        submit_attempt=int(package.get("submit_attempt", 1) or 1),
                        payload=dict(package),
                    )
                )


async def _import_access() -> None:
    path = _LEGACY_FILES["access"]
    if not path.exists():
        return
    data = read_json(path, {"users": {}})
    async with session_scope() as session:
        for raw_id, profile in (data.get("users") or {}).items():
            if not str(raw_id).isdigit():
                continue
            session.add(
                AccessProfile(
                    user_id=int(raw_id),
                    can_notify=bool(profile.get("can_notify")),
                    can_review=bool(profile.get("can_review")),
                    can_broadcast=bool(profile.get("can_broadcast", False)),
                    is_admin=bool(profile.get("is_admin")),
                    faculties=list(profile.get("faculties", [])),
                    groups=list(profile.get("groups", [])),
                    specialties=list(profile.get("specialties", profile.get("groups", []))),
                )
            )


async def _import_study_groups() -> None:
    path = _LEGACY_FILES["study_groups"]
    if not path.exists():
        return
    data = read_json(path, {"groups": []})
    async with session_scope() as session:
        for row in data.get("groups", []):
            session.add(
                StudyGroup(
                    track=str(row.get("track", "uni")).lower(),
                    faculty=str(row.get("faculty", "")),
                    specialty=str(row.get("specialty", "")),
                    course=str(row.get("course", "")),
                    group_name=str(row.get("group_name", "")),
                    created_by=int(row.get("created_by", 0) or 0),
                )
            )


async def _import_support() -> None:
    path = _LEGACY_FILES["support"]
    if not path.exists():
        return
    data = read_json(
        path,
        {"seq_ticket": 10000, "user_aliases": {}, "tickets": {}, "message_links": {}, "blocked_actors": {}, "staff_registry": {}},
    )
    async with session_scope() as session:
        session.add(
            SupportMeta(
                id=1,
                seq_ticket=int(data.get("seq_ticket", 10000)),
                user_aliases=dict(data.get("user_aliases", {})),
                message_links=dict(data.get("message_links", {})),
                blocked_actors=dict(data.get("blocked_actors", {})),
                staff_registry=dict(data.get("staff_registry", {})),
            )
        )
        for ticket_id, ticket in (data.get("tickets") or {}).items():
            body = dict(ticket)
            body.setdefault("ticket_id", str(ticket_id))
            row, _ = support_ticket_from_payload(str(ticket_id), body)
            session.add(row)
