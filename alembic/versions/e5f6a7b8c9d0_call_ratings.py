"""call_ratings

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-15 19:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'e5f6a7b8c9d0'
down_revision: str | Sequence[str] | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'call_ratings',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('call_id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=False),
        sa.Column('call_score', sa.Integer(), nullable=False),
        sa.Column('app_score', sa.Integer(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('call_score BETWEEN 1 AND 5', name='ck_call_rating_call_score'),
        sa.CheckConstraint('app_score IS NULL OR app_score BETWEEN 1 AND 5', name='ck_call_rating_app_score'),
        sa.ForeignKeyConstraint(['call_id'], ['call_logs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_call_ratings_call_id'), 'call_ratings', ['call_id'])
    op.create_index(op.f('ix_call_ratings_user_id'), 'call_ratings', ['user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_call_ratings_user_id'), table_name='call_ratings')
    op.drop_index(op.f('ix_call_ratings_call_id'), table_name='call_ratings')
    op.drop_table('call_ratings')
