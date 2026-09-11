"""channel : colonne category (tri / filtre des chaines)

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-10

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("category", sa.String(24), nullable=True))
    op.create_index("ix_groups_category", "groups", ["category"])


def downgrade() -> None:
    op.drop_index("ix_groups_category", table_name="groups")
    op.drop_column("groups", "category")
