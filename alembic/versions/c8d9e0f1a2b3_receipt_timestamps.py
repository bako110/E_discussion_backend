"""message_receipts : delivered_at / read_at / played_at (ecran Infos)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-10

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_receipts",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "message_receipts",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "message_receipts",
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
    )
    # backfill : on approxime avec les timestamps existants
    op.execute(
        "UPDATE message_receipts SET delivered_at = COALESCE(created_at, updated_at)"
    )
    op.execute(
        "UPDATE message_receipts SET read_at = updated_at WHERE state = 'read'"
    )
    # NB : 'played' est un horodatage a part (played_at), la colonne `state`
    # reste 'delivered' | 'read' -> pas besoin de toucher a l'enum PG.


def downgrade() -> None:
    op.drop_column("message_receipts", "played_at")
    op.drop_column("message_receipts", "read_at")
    op.drop_column("message_receipts", "delivered_at")
