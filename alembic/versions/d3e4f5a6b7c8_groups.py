"""groups & channels : tables groups / group_members / group_messages

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-08

    alembic upgrade head
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.types import GUID

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Idempotence : un run precedent a pu laisser les types ENUM.
    bind.exec_driver_sql("DROP TYPE IF EXISTS groupkind CASCADE")
    bind.exec_driver_sql("DROP TYPE IF EXISTS grouprole CASCADE")
    bind.exec_driver_sql("CREATE TYPE groupkind AS ENUM ('group', 'channel')")
    bind.exec_driver_sql(
        "CREATE TYPE grouprole AS ENUM ('owner', 'admin', 'member', 'subscriber')"
    )
    kind_col = postgresql.ENUM("group", "channel", name="groupkind", create_type=False)
    role_col = postgresql.ENUM(
        "owner", "admin", "member", "subscriber", name="grouprole", create_type=False
    )

    op.create_table(
        "groups",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("kind", kind_col, nullable=False, server_default="group"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
        sa.Column("owner_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invite_code", sa.String(16), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_groups_owner_id", "groups", ["owner_id"])
    op.create_index("ix_groups_invite_code", "groups", ["invite_code"], unique=True)
    op.create_index("ix_groups_last_message_at", "groups", ["last_message_at"])

    op.create_table(
        "group_members",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("group_id", GUID(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", role_col, nullable=False, server_default="member"),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    op.create_table(
        "group_messages",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("group_id", GUID(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachment_url", sa.String(1024), nullable=True),
        sa.Column("attachment_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("client_id", sa.String(64), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "client_id", name="uq_group_msg_client"),
    )
    op.create_index("ix_group_messages_group_id", "group_messages", ["group_id"])
    op.create_index("ix_group_messages_sender_id", "group_messages", ["sender_id"])
    op.create_index("ix_group_messages_client_id", "group_messages", ["client_id"])


def downgrade() -> None:
    op.drop_table("group_messages")
    op.drop_table("group_members")
    op.drop_table("groups")
    sa.Enum(name="grouprole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="groupkind").drop(op.get_bind(), checkfirst=True)
