"""channel_discussion_and_subscription

Revision ID: c9d8e7f6a5b4
Revises: ada02700e267
Create Date: 2026-09-15 10:00:00.000000
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'c9d8e7f6a5b4'
down_revision: str | Sequence[str] | None = 'ada02700e267'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'groups',
        sa.Column('discussion_group_id', GUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_groups_discussion_group_id',
        'groups',
        'groups',
        ['discussion_group_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_groups_discussion_group_id', 'groups', ['discussion_group_id']
    )

    op.add_column(
        'groups',
        sa.Column('is_paid', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('groups', 'is_paid', server_default=None)
    op.add_column(
        'groups',
        sa.Column('subscription_price_cents', sa.Integer(), nullable=True),
    )
    op.add_column(
        'groups',
        sa.Column('subscription_currency', sa.String(length=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('groups', 'subscription_currency')
    op.drop_column('groups', 'subscription_price_cents')
    op.drop_column('groups', 'is_paid')
    op.drop_index('ix_groups_discussion_group_id', table_name='groups')
    op.drop_constraint('fk_groups_discussion_group_id', 'groups', type_='foreignkey')
    op.drop_column('groups', 'discussion_group_id')
