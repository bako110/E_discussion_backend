"""group_sign_messages

Revision ID: 9f68f5c8e29e
Revises: a0aecb9519dc
Create Date: 2026-09-14 12:55:20.898558
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = '9f68f5c8e29e'
down_revision: str | Sequence[str] | None = 'a0aecb9519dc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'groups',
        sa.Column('sign_messages', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('groups', 'sign_messages', server_default=None)


def downgrade() -> None:
    op.drop_column('groups', 'sign_messages')
