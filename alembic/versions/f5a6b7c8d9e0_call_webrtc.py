"""call_logs : statut + room LiveKit + E2EE key + horodatages appel

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-09

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None

_STATUSES = ("ringing", "active", "ended", "missed", "rejected", "cancelled", "failed")


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TYPE IF EXISTS callstatus CASCADE")
    values = ", ".join(f"'{s}'" for s in _STATUSES)
    bind.exec_driver_sql(f"CREATE TYPE callstatus AS ENUM ({values})")
    status_col = sa.Enum(*_STATUSES, name="callstatus", create_type=False)

    op.add_column(
        "call_logs",
        sa.Column("status", status_col, nullable=False, server_default="ringing"),
    )
    op.add_column(
        "call_logs",
        sa.Column("room_name", sa.String(80), nullable=True),
    )
    op.add_column("call_logs", sa.Column("e2ee_key", sa.String(128), nullable=True))
    op.add_column("call_logs", sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("call_logs", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))

    # backfill room_name pour les lignes existantes (aucune en pratique)
    bind.exec_driver_sql(
        "UPDATE call_logs SET room_name = 'legacy_' || id::text WHERE room_name IS NULL"
    )
    op.alter_column("call_logs", "room_name", nullable=False)
    op.create_index("ix_call_logs_room_name", "call_logs", ["room_name"], unique=True)

    # 'direction' devient optionnel (defaut 'outgoing')
    op.alter_column(
        "call_logs",
        "direction",
        server_default="outgoing",
        existing_type=sa.Enum("incoming", "outgoing", "missed", name="calldirection"),
    )


def downgrade() -> None:
    op.drop_index("ix_call_logs_room_name", "call_logs")
    op.drop_column("call_logs", "ended_at")
    op.drop_column("call_logs", "answered_at")
    op.drop_column("call_logs", "e2ee_key")
    op.drop_column("call_logs", "room_name")
    op.drop_column("call_logs", "status")
    sa.Enum(name="callstatus").drop(op.get_bind(), checkfirst=True)
