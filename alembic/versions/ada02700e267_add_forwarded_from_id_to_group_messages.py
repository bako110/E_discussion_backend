"""add forwarded_from_id to group_messages

Revision ID: ada02700e267
Revises: 7519ab236f06
Create Date: 2026-09-15 11:41:26.109828
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'ada02700e267'
down_revision: str | Sequence[str] | None = '7519ab236f06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('group_messages', sa.Column('forwarded_from_id', GUID(), nullable=True))


def downgrade() -> None:
    op.drop_column('group_messages', 'forwarded_from_id')
