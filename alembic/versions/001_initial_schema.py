"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("fio", sa.String(length=255), server_default=""),
        sa.Column("role", sa.String(length=64), server_default=""),
        sa.Column("faculty", sa.String(length=255), server_default="-"),
        sa.Column("specialty", sa.String(length=255), server_default="-"),
        sa.Column("course", sa.String(length=64), server_default="-"),
        sa.Column("group", sa.String(length=128), server_default="-"),
        sa.Column("admission_track", sa.String(length=16), server_default="uni"),
        sa.Column("is_grant", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("submit_attempt", sa.Integer(), server_default="1"),
        sa.Column("responsible_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by_username", sa.String(length=128), server_default=""),
        sa.Column("tg_username", sa.String(length=128), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_registrations_tg_user_id", "registrations", ["tg_user_id"])
    op.create_index("ix_registrations_phone", "registrations", ["phone"])
    op.create_index("ix_registrations_status", "registrations", ["status"])

    op.create_table(
        "document_packages",
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column("submit_attempt", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("tg_user_id"),
    )

    op.create_table(
        "access_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("can_notify", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_review", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_broadcast", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("faculties", postgresql.JSONB(astext_type=sa.Text()), server_default="[]"),
        sa.Column("groups", postgresql.JSONB(astext_type=sa.Text()), server_default="[]"),
        sa.Column("specialties", postgresql.JSONB(astext_type=sa.Text()), server_default="[]"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "study_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("track", sa.String(length=16), nullable=False),
        sa.Column("faculty", sa.String(length=255), nullable=False),
        sa.Column("specialty", sa.String(length=255), nullable=False),
        sa.Column("course", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.BigInteger(), server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track", "faculty", "specialty", "course", "group_name", name="uq_study_group"),
    )

    op.create_table(
        "support_tickets",
        sa.Column("ticket_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_code", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("anonymous", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("ticket_id"),
    )

    op.create_table(
        "support_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seq_ticket", sa.Integer(), server_default="10000"),
        sa.Column("user_aliases", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("message_links", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("blocked_actors", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("staff_registry", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "schema_migration_flags",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("schema_migration_flags")
    op.drop_table("audit_events")
    op.drop_table("support_meta")
    op.drop_table("support_tickets")
    op.drop_table("study_groups")
    op.drop_table("access_profiles")
    op.drop_table("document_packages")
    op.drop_index("ix_registrations_status", table_name="registrations")
    op.drop_index("ix_registrations_phone", table_name="registrations")
    op.drop_index("ix_registrations_tg_user_id", table_name="registrations")
    op.drop_table("registrations")
