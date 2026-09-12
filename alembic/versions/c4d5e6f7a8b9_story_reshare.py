"""stories : reshared_from_id (repartage d'un statut existant)

Revision ID: c4d5e6f7a8b9
Revises: b3d4e5f6a7b8
Create Date: 2026-09-12

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

revision = "c4d5e6f7a8b9"
down_revision = "b3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("reshared_from_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_stories_reshared_from_id",
        "stories",
        "stories",
        ["reshared_from_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_stories_reshared_from_id", "stories", type_="foreignkey")
    op.drop_column("stories", "reshared_from_id")
