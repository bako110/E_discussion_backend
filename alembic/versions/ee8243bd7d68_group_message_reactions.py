"""group_message_reactions

Revision ID: ee8243bd7d68
Revises: 9f68f5c8e29e
Create Date: 2026-09-14 13:21:34.657364
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'ee8243bd7d68'
down_revision: str | Sequence[str] | None = '9f68f5c8e29e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'group_message_reactions',
        sa.Column('message_id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=False),
        sa.Column('emoji', sa.String(length=16), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['group_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_group_reaction_msg_user'),
    )
    op.create_index(
        op.f('ix_group_message_reactions_message_id'),
        'group_message_reactions',
        ['message_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_group_message_reactions_message_id'), table_name='group_message_reactions')
    op.drop_table('group_message_reactions')
