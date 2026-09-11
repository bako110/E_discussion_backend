"""conversation_hides : suppression de conversation cote utilisateur

Revision ID: a2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-11

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a2c3d4e5f6a7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

GUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "conversation_hides",
        sa.Column("id", GUID, primary_key=True),
        sa.Column(
            "user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "conversation_id",
            GUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "conversation_id", name="uq_hide_user_conv"),
    )
    op.create_index("ix_conversation_hides_user_id", "conversation_hides", ["user_id"])
    op.create_index(
        "ix_conversation_hides_conversation_id", "conversation_hides", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_hides_conversation_id", table_name="conversation_hides")
    op.drop_index("ix_conversation_hides_user_id", table_name="conversation_hides")
    op.drop_table("conversation_hides")
