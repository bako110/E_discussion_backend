"""story audience : mode (contacts / contacts_except / only) + liste de contacts

Revision ID: a6b7c8d9e0f1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

revision = "a6b7c8d9e0f1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "story_audience_mode",
            sa.String(20),
            nullable=False,
            server_default="contacts",
        ),
    )
    op.create_table(
        "story_audience_entries",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("owner_id", GUID(), nullable=False),
        sa.Column("target_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "target_id", name="uq_story_audience"),
    )
    op.create_index(
        "ix_story_audience_entries_owner_id", "story_audience_entries", ["owner_id"]
    )
    op.create_index(
        "ix_story_audience_entries_target_id", "story_audience_entries", ["target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_story_audience_entries_target_id", "story_audience_entries")
    op.drop_index("ix_story_audience_entries_owner_id", "story_audience_entries")
    op.drop_table("story_audience_entries")
    op.drop_column("users", "story_audience_mode")
