"""story_viewer_mutes

Revision ID: af1b0cabd3b0
Revises: 1570f275f4f2
Create Date: 2026-09-19 13:28:32.867122
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

from app.db.types import GUID

revision: str = 'af1b0cabd3b0'
down_revision: str | Sequence[str] | None = '1570f275f4f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_viewer_mutes",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("muter_id", GUID(), nullable=False),
        sa.Column("muted_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["muter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["muted_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("muter_id", "muted_id", name="uq_story_viewer_mute"),
    )
    op.create_index("ix_story_viewer_mutes_muter_id", "story_viewer_mutes", ["muter_id"])
    op.create_index("ix_story_viewer_mutes_muted_id", "story_viewer_mutes", ["muted_id"])


def downgrade() -> None:
    op.drop_index("ix_story_viewer_mutes_muted_id", "story_viewer_mutes")
    op.drop_index("ix_story_viewer_mutes_muter_id", "story_viewer_mutes")
    op.drop_table("story_viewer_mutes")
