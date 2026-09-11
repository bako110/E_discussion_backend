"""channel_live

Revision ID: ea6df3845ff9
Revises: b3d4e5f6a7b8
Create Date: 2026-09-11 20:21:50.670800
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'ea6df3845ff9'
down_revision: str | Sequence[str] | None = 'b3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'channel_lives',
        sa.Column('group_id', GUID(), nullable=False),
        sa.Column('started_by', GUID(), nullable=False),
        sa.Column('status', sa.Enum('live', 'ended', name='channellivestatus'), nullable=False),
        sa.Column('room_name', sa.String(length=80), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=True),
        sa.Column('peak_viewers', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['started_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_channel_lives_group_id'), 'channel_lives', ['group_id'], unique=False)
    op.create_index(op.f('ix_channel_lives_room_name'), 'channel_lives', ['room_name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_lives_room_name'), table_name='channel_lives')
    op.drop_index(op.f('ix_channel_lives_group_id'), table_name='channel_lives')
    op.drop_table('channel_lives')
