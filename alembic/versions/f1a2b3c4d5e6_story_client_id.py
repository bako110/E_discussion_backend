"""stories : client_id (idempotence offline)

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-09-11

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("client_id", sa.String(64), nullable=True))
    op.create_index(
        "ix_stories_author_client",
        "stories",
        ["author_id", "client_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_stories_author_client", table_name="stories")
    op.drop_column("stories", "client_id")
