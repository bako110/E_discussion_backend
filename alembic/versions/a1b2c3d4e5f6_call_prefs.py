"""user : préférences d'appel (ringtone, vibreur, HP, low-data, block-unknown)

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-09-09

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("call_ringtone", sa.String(16), nullable=False, server_default="default"),
    )
    op.add_column(
        "users",
        sa.Column("call_vibrate", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column(
            "call_answer_on_speaker", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "users",
        sa.Column("call_low_data", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column(
            "call_block_unknown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    for col in (
        "call_block_unknown",
        "call_low_data",
        "call_answer_on_speaker",
        "call_vibrate",
        "call_ringtone",
    ):
        op.drop_column("users", col)
