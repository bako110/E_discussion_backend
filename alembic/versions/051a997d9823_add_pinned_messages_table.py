"""add pinned_messages table

Revision ID: 051a997d9823
Revises: c9d8e7f6a5b4
Create Date: 2026-09-15 16:21:09.812340
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = '051a997d9823'
down_revision: str | Sequence[str] | None = 'c9d8e7f6a5b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'pinned_messages',
        sa.Column('conversation_id', GUID(), nullable=True),
        sa.Column('group_id', GUID(), nullable=True),
        sa.Column('message_id', GUID(), nullable=False),
        sa.Column('pinned_by', GUID(), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pinned_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', name='uq_pinned_message'),
    )
    op.create_index(op.f('ix_pinned_messages_conversation_id'), 'pinned_messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_pinned_messages_group_id'), 'pinned_messages', ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pinned_messages_group_id'), table_name='pinned_messages')
    op.drop_index(op.f('ix_pinned_messages_conversation_id'), table_name='pinned_messages')
    op.drop_table('pinned_messages')
