"""merge channel_live and story reshare heads

Revision ID: a0aecb9519dc
Revises: ea6df3845ff9, c4d5e6f7a8b9
Create Date: 2026-09-12 14:48:11.836210
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = 'a0aecb9519dc'
down_revision: str | Sequence[str] | None = ('ea6df3845ff9', 'c4d5e6f7a8b9')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
