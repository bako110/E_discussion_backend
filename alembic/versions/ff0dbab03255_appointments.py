"""appointments : rendez-vous multi-participants + rappels

Revision ID: ff0dbab03255
Revises: f6a7b8c9d0e1
Create Date: 2026-09-17 16:10:21.372623
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = 'ff0dbab03255'
down_revision: str | Sequence[str] | None = 'f6a7b8c9d0e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'appointments',
        sa.Column('organizer_id', GUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('location_map_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.Enum('scheduled', 'cancelled', name='appointmentstatus'), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organizer_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_appointments_organizer_id'), 'appointments', ['organizer_id'], unique=False)
    op.create_index(op.f('ix_appointments_scheduled_at'), 'appointments', ['scheduled_at'], unique=False)

    op.create_table(
        'appointment_participants',
        sa.Column('appointment_id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'accepted', 'declined', name='appointmentparticipantstatus'), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', GUID(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', 'user_id', name='uq_appointment_participant'),
    )
    op.create_index(
        op.f('ix_appointment_participants_appointment_id'),
        'appointment_participants',
        ['appointment_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_appointment_participants_user_id'),
        'appointment_participants',
        ['user_id'],
        unique=False,
    )

    op.create_table(
        'appointment_reminders',
        sa.Column('appointment_id', GUID(), nullable=False),
        sa.Column('kind', sa.Enum('h24', 'h1', 'at_time', name='appointmentreminderkind'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', 'kind', name='uq_appointment_reminder_kind'),
    )
    op.create_index(
        op.f('ix_appointment_reminders_appointment_id'),
        'appointment_reminders',
        ['appointment_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_appointment_reminders_appointment_id'), table_name='appointment_reminders')
    op.drop_table('appointment_reminders')
    op.drop_index(op.f('ix_appointment_participants_user_id'), table_name='appointment_participants')
    op.drop_index(op.f('ix_appointment_participants_appointment_id'), table_name='appointment_participants')
    op.drop_table('appointment_participants')
    op.drop_index(op.f('ix_appointments_scheduled_at'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_organizer_id'), table_name='appointments')
    op.drop_table('appointments')
