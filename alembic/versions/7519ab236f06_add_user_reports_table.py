"""add user_reports table

Revision ID: 7519ab236f06
Revises: ee8243bd7d68
Create Date: 2026-09-14 16:37:06.687851
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = '7519ab236f06'
down_revision: str | Sequence[str] | None = 'ee8243bd7d68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user_reports',
        sa.Column('reporter_id', GUID(), nullable=False),
        sa.Column('reported_id', GUID(), nullable=False),
        sa.Column('reason', sa.Enum('spam', 'harassment', 'fake_profile', 'inappropriate_content', 'scam', 'other', name='reportreason'), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['reported_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_reports_reported_id'), 'user_reports', ['reported_id'], unique=False)
    op.create_index(op.f('ix_user_reports_reporter_id'), 'user_reports', ['reporter_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_reports_reporter_id'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_reported_id'), table_name='user_reports')
    op.drop_table('user_reports')
