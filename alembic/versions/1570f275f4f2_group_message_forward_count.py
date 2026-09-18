"""group_message_forward_count

Revision ID: 1570f275f4f2
Revises: 197a24c6c673
Create Date: 2026-09-18 10:19:23.808948
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = '1570f275f4f2'
down_revision: str | Sequence[str] | None = '197a24c6c673'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_messages",
        sa.Column("forward_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("group_messages", "forward_count")
