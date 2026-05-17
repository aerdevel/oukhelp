"""Схема PostgreSQL: нормализованные сущности + JSONB для гибких полей пакетов/тикетов."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Registration(Base):
    """Регистрация пользователя (pending / approved / denied)."""

    __tablename__ = "registrations"
    __table_args__ = (
        Index("ix_registrations_status_created", "status", "created_at"),
        Index("ix_registrations_track_role", "admission_track", "role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    fio: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(64), default="")
    faculty: Mapped[str] = mapped_column(String(255), default="-")
    specialty: Mapped[str] = mapped_column(String(255), default="-")
    course: Mapped[str] = mapped_column(String(64), default="-")
    group: Mapped[str] = mapped_column(String(128), default="-")
    admission_track: Mapped[str] = mapped_column(String(16), default="uni")
    is_grant: Mapped[bool] = mapped_column(Boolean, default=False)
    submit_attempt: Mapped[int] = mapped_column(Integer, default=1)
    responsible_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by_username: Mapped[str] = mapped_column(String(128), default="")
    tg_username: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class DocumentPackage(Base):
    """Пакет документов абитуриента (одна активная запись на tg_user_id в pending)."""

    __tablename__ = "document_packages"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    submit_attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AccessProfile(Base):
    """Права сотрудника и ACL-списки (кафедра / группа / специальность)."""

    __tablename__ = "access_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    can_notify: Mapped[bool] = mapped_column(Boolean, default=False)
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    can_broadcast: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    faculties: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    groups: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    specialties: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class StudyGroup(Base):
    __tablename__ = "study_groups"
    __table_args__ = (
        UniqueConstraint("track", "faculty", "specialty", "course", "group_name", name="uq_study_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    faculty: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course: Mapped[str] = mapped_column(String(64), nullable=False)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)


class SupportTicket(Base):
    """Тикет поддержки; вложенные messages/chat_messages — в payload (JSONB)."""

    __tablename__ = "support_tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    topic_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SupportMeta(Base):
    """Служебное состояние поддержки (счётчик id, алиасы, блокировки, реестр staff)."""

    __tablename__ = "support_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seq_ticket: Mapped[int] = mapped_column(Integer, default=10000)
    user_aliases: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    message_links: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    blocked_actors: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    staff_registry: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class GroupSchedulePhoto(Base):
    """Фото расписания на неделю для группы (одна актуальная запись на трек+группу)."""

    __tablename__ = "group_schedule_photos"
    __table_args__ = (UniqueConstraint("admission_track", "group_name", name="uq_schedule_photo_group_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    admission_track: Mapped[str] = mapped_column(String(16), default="uni", index=True)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_kind: Mapped[str] = mapped_column(String(16), default="photo")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StaffScheduleEntry(Base):
    """Пара расписания, созданная ответственным для своих групп."""

    __tablename__ = "staff_schedule_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    admission_track: Mapped[str] = mapped_column(String(16), default="uni", index=True)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    weekday: Mapped[str] = mapped_column(String(32), nullable=False)
    lesson_time: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    room: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SchemaMigrationFlag(Base):
    """Маркер однократного импорта legacy JSON в PostgreSQL."""

    __tablename__ = "schema_migration_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
