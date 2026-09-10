"""privacy audience : online_privacy + table privacy_audience (liste par champ)

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-10

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # elargit les colonnes existantes (nouveaux modes 'everyone_except' / 'only')
    op.alter_column(
        "users", "last_seen_privacy",
        type_=sa.String(20), existing_type=sa.String(16), existing_nullable=False,
    )
    op.alter_column(
        "users", "profile_photo_privacy",
        type_=sa.String(20), existing_type=sa.String(16), existing_nullable=False,
    )
    op.alter_column(
        "users", "about_privacy",
        type_=sa.String(20), existing_type=sa.String(16), existing_nullable=False,
    )
    # reglage "en ligne" dedie — par defaut il suit la derniere connexion
    op.add_column(
        "users",
        sa.Column(
            "online_privacy",
            sa.String(20),
            nullable=False,
            server_default="match_last_seen",
        ),
    )
    op.create_table(
        "privacy_audience",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("owner_id", GUID(), nullable=False),
        sa.Column("field", sa.String(20), nullable=False),
        sa.Column("target_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "field", "target_id", name="uq_privacy_audience"),
    )
    op.create_index("ix_privacy_audience_owner_id", "privacy_audience", ["owner_id"])
    op.create_index("ix_privacy_audience_field", "privacy_audience", ["field"])
    op.create_index("ix_privacy_audience_target_id", "privacy_audience", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_privacy_audience_target_id", "privacy_audience")
    op.drop_index("ix_privacy_audience_field", "privacy_audience")
    op.drop_index("ix_privacy_audience_owner_id", "privacy_audience")
    op.drop_table("privacy_audience")
    op.drop_column("users", "online_privacy")
    op.alter_column(
        "users", "about_privacy",
        type_=sa.String(16), existing_type=sa.String(20), existing_nullable=False,
    )
    op.alter_column(
        "users", "profile_photo_privacy",
        type_=sa.String(16), existing_type=sa.String(20), existing_nullable=False,
    )
    op.alter_column(
        "users", "last_seen_privacy",
        type_=sa.String(16), existing_type=sa.String(20), existing_nullable=False,
    )
