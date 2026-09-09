"""user privacy : last_seen/photo/about visibility + read_receipts

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-08

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_privacy", sa.String(16), nullable=False, server_default="everyone"),
    )
    op.add_column(
        "users",
        sa.Column("profile_photo_privacy", sa.String(16), nullable=False, server_default="everyone"),
    )
    op.add_column(
        "users",
        sa.Column("about_privacy", sa.String(16), nullable=False, server_default="everyone"),
    )
    op.add_column(
        "users",
        sa.Column("read_receipts", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "read_receipts")
    op.drop_column("users", "about_privacy")
    op.drop_column("users", "profile_photo_privacy")
    op.drop_column("users", "last_seen_privacy")
