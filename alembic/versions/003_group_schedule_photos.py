"""group schedule photos (weekly image per group)

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_schedule_photos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("admission_track", sa.String(length=16), server_default="uni", nullable=False),
        sa.Column("group_name", sa.String(length=128), nullable=False),
        sa.Column("photo_file_id", sa.String(length=255), nullable=False),
        sa.Column("photo_kind", sa.String(length=16), server_default="photo"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admission_track", "group_name", name="uq_schedule_photo_group_track"),
    )
    op.create_index("ix_schedule_photo_group", "group_schedule_photos", ["group_name"])


def downgrade() -> None:
    op.drop_index("ix_schedule_photo_group", table_name="group_schedule_photos")
    op.drop_table("group_schedule_photos")
