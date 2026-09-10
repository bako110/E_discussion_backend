"""group settings : politiques + approbation + visibilite invite + disappearing

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-10

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import GUID

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column("send_messages_policy", sa.String(10), nullable=False, server_default="all"),
    )
    op.add_column(
        "groups",
        sa.Column("edit_info_policy", sa.String(10), nullable=False, server_default="admins"),
    )
    op.add_column(
        "groups",
        sa.Column("add_members_policy", sa.String(10), nullable=False, server_default="all"),
    )
    op.add_column(
        "groups",
        sa.Column(
            "join_approval_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "groups",
        sa.Column("invite_visibility", sa.String(10), nullable=False, server_default="both"),
    )
    op.add_column(
        "groups",
        sa.Column("disappearing_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "group_join_requests",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("group_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_join_req"),
    )
    op.create_index(
        "ix_group_join_requests_group_id", "group_join_requests", ["group_id"]
    )
    op.create_index(
        "ix_group_join_requests_user_id", "group_join_requests", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_group_join_requests_user_id", "group_join_requests")
    op.drop_index("ix_group_join_requests_group_id", "group_join_requests")
    op.drop_table("group_join_requests")
    op.drop_column("groups", "disappearing_seconds")
    op.drop_column("groups", "invite_visibility")
    op.drop_column("groups", "join_approval_required")
    op.drop_column("groups", "add_members_policy")
    op.drop_column("groups", "edit_info_policy")
    op.drop_column("groups", "send_messages_policy")
