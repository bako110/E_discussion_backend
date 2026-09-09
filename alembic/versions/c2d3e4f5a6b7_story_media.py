"""story : audio/voice media types + audio_url/audio_name/audience colonnes

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-08

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # nouveaux membres de l'enum
    bind.exec_driver_sql("ALTER TYPE storymediatype ADD VALUE IF NOT EXISTS 'audio'")
    bind.exec_driver_sql("ALTER TYPE storymediatype ADD VALUE IF NOT EXISTS 'voice'")

    op.add_column("stories", sa.Column("audio_url", sa.String(1024), nullable=True))
    op.add_column("stories", sa.Column("audio_name", sa.String(120), nullable=True))
    op.add_column(
        "stories",
        sa.Column("audience", sa.String(16), nullable=False, server_default="everyone"),
    )


def downgrade() -> None:
    op.drop_column("stories", "audience")
    op.drop_column("stories", "audio_name")
    op.drop_column("stories", "audio_url")
    # NB : on ne retire pas les valeurs 'audio'/'voice' de l'enum (Postgres ne
    # le permet pas simplement) — sans effet si inutilisees.
