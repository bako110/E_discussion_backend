"""stories : tables stories / story_views / story_reactions + messages.story_id

Revision ID: b1c2d3e4f5a6
Revises: 3a95a00e2568
Create Date: 2026-09-08

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.types import GUID

revision = "b1c2d3e4f5a6"
down_revision = "3a95a00e2568"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Idempotence : un run precedent a pu laisser le type ENUM.
    bind.exec_driver_sql("DROP TYPE IF EXISTS storymediatype CASCADE")
    bind.exec_driver_sql(
        "CREATE TYPE storymediatype AS ENUM ('text', 'image', 'video')"
    )
    # postgresql.ENUM avec create_type=False : reference le type deja cree,
    # n'emet JAMAIS de CREATE TYPE (contrairement a sa.Enum dans create_table).
    story_media_col = postgresql.ENUM(
        "text", "image", "video", name="storymediatype", create_type=False
    )

    op.create_table(
        "stories",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("author_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_type", story_media_col, nullable=False, server_default="text"),
        sa.Column("media_url", sa.String(1024), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("background_color", sa.String(16), nullable=True),
        sa.Column("font", sa.String(32), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("thumbnail_url", sa.String(1024), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stories_author_id", "stories", ["author_id"])
    op.create_index("ix_stories_expires_at", "stories", ["expires_at"])

    op.create_table(
        "story_views",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("story_id", GUID(), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewer_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("story_id", "viewer_id", name="uq_story_view"),
    )
    op.create_index("ix_story_views_story_id", "story_views", ["story_id"])
    op.create_index("ix_story_views_viewer_id", "story_views", ["viewer_id"])

    op.create_table(
        "story_reactions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("story_id", GUID(), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("story_id", "user_id", name="uq_story_reaction"),
    )
    op.create_index("ix_story_reactions_story_id", "story_reactions", ["story_id"])
    op.create_index("ix_story_reactions_user_id", "story_reactions", ["user_id"])

    op.add_column(
        "messages",
        sa.Column(
            "story_id",
            GUID(),
            sa.ForeignKey("stories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_messages_story_id", "messages", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_story_id", "messages")
    op.drop_column("messages", "story_id")
    op.drop_table("story_reactions")
    op.drop_table("story_views")
    op.drop_table("stories")
    sa.Enum(name="storymediatype").drop(op.get_bind(), checkfirst=True)
