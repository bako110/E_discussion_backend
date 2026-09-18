"""appointment_notes_and_hide

Revision ID: 197a24c6c673
Revises: d5180e429ed7
Create Date: 2026-09-18 09:57:00.634918
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = '197a24c6c673'
down_revision: str | Sequence[str] | None = 'd5180e429ed7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NB : seules les tables des deux nouvelles fonctionnalites (notes +
    # masquage personnel) sont incluses ici. L'autogenerate initial a aussi
    # detecte un drift preexistant et sans rapport sur device_tokens/
    # messages/refresh_tokens/users (unique=True vs unique=False sur des
    # index deja en place) — volontairement omis : pas notre scope, a traiter
    # dans une migration dediee si besoin.
    op.create_table(
        'appointment_hidden_by_user',
        sa.Column('appointment_id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=False),
        sa.Column('hidden_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', 'user_id', name='uq_appointment_hidden_user'),
    )
    op.create_index(
        op.f('ix_appointment_hidden_by_user_appointment_id'),
        'appointment_hidden_by_user',
        ['appointment_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_appointment_hidden_by_user_user_id'),
        'appointment_hidden_by_user',
        ['user_id'],
        unique=False,
    )
    op.create_table(
        'appointment_notes',
        sa.Column('appointment_id', GUID(), nullable=False),
        sa.Column('author_id', GUID(), nullable=False),
        sa.Column(
            'visibility',
            sa.Enum('private', 'public', name='appointmentnotevisibility'),
            nullable=False,
        ),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_appointment_notes_appointment_id'),
        'appointment_notes',
        ['appointment_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_appointment_notes_author_id'), 'appointment_notes', ['author_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_appointment_notes_author_id'), table_name='appointment_notes')
    op.drop_index(op.f('ix_appointment_notes_appointment_id'), table_name='appointment_notes')
    op.drop_table('appointment_notes')
    op.drop_index(
        op.f('ix_appointment_hidden_by_user_user_id'), table_name='appointment_hidden_by_user'
    )
    op.drop_index(
        op.f('ix_appointment_hidden_by_user_appointment_id'),
        table_name='appointment_hidden_by_user',
    )
    op.drop_table('appointment_hidden_by_user')
