"""staff schedule entries

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_schedule_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("admission_track", sa.String(length=16), server_default="uni"),
        sa.Column("group_name", sa.String(length=128), nullable=False),
        sa.Column("weekday", sa.String(length=32), nullable=False),
        sa.Column("lesson_time", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("room", sa.String(length=128), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_staff_schedule_group", "staff_schedule_entries", ["group_name"])
    op.create_index("ix_staff_schedule_creator", "staff_schedule_entries", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_staff_schedule_creator", table_name="staff_schedule_entries")
    op.drop_index("ix_staff_schedule_group", table_name="staff_schedule_entries")
    op.drop_table("staff_schedule_entries")
