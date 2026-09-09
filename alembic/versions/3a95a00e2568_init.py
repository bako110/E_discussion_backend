"""init — schema v1 (users, auth, conversations, messages, devices E2E, push, calls)

Revision ID: 3a95a00e2568
Revises:
Create Date: 2026-09-07

Migration ecrite a la main a partir des modeles (`app/db/models`). Pour
regenerer apres modification d'un modele :
    alembic revision --autogenerate -m "..."
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "3a95a00e2568"
down_revision = None
branch_labels = None
depends_on = None

GUID = postgresql.UUID(as_uuid=True)


def _ts(t: sa.Table) -> None:  # pragma: no cover - helper inline
    ...


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("email", sa.String(255), unique=True),
        sa.Column("phone", sa.String(32), unique=True),
        sa.Column("username", sa.String(32), unique=True),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("display_name", sa.String(80)),
        sa.Column("avatar_url", sa.String(512)),
        sa.Column("about", sa.Text()),
        sa.Column("locale", sa.String(8), nullable=False, server_default="fr"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("device_name", sa.String(120)),
        sa.Column("platform", sa.String(20)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"])

    otp_channel = sa.Enum("email", "sms", name="otpchannel")
    otp_purpose = sa.Enum(
        "register", "login", "link_phone", "link_email", "reset_password", name="otppurpose"
    )
    op.create_table(
        "otp_challenges",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("channel", otp_channel, nullable=False),
        sa.Column("purpose", otp_purpose, nullable=False),
        sa.Column("identifier", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_otp_challenges_identifier", "otp_challenges", ["identifier"])
    op.create_index("ix_otp_challenges_user_id", "otp_challenges", ["user_id"])

    op.create_table(
        "user_contacts",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("owner_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("matched_user_id", GUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "phone", name="uq_contact_owner_phone"),
    )
    op.create_index("ix_user_contacts_owner_id", "user_contacts", ["owner_id"])
    op.create_index("ix_user_contacts_phone", "user_contacts", ["phone"])
    op.create_index("ix_user_contacts_matched_user_id", "user_contacts", ["matched_user_id"])

    op.create_table(
        "user_blocks",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("blocker_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blocked_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_block_pair"),
    )
    op.create_index("ix_user_blocks_blocker_id", "user_blocks", ["blocker_id"])
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    op.create_table(
        "conversations",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("user_a_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_b_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_conversation_pair"),
    )
    op.create_index("ix_conversations_user_a_id", "conversations", ["user_a_id"])
    op.create_index("ix_conversations_user_b_id", "conversations", ["user_b_id"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])

    req_status = sa.Enum("pending", "accepted", "declined", name="requeststatus")
    op.create_table(
        "conversation_requests",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("requester_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", req_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requester_id", "target_id", name="uq_request_pair"),
    )
    op.create_index("ix_conversation_requests_requester_id", "conversation_requests", ["requester_id"])
    op.create_index("ix_conversation_requests_target_id", "conversation_requests", ["target_id"])

    op.create_table(
        "conversation_mutes",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", GUID, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("muted_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "conversation_id", name="uq_mute_user_conv"),
    )
    op.create_index("ix_conversation_mutes_user_id", "conversation_mutes", ["user_id"])
    op.create_index("ix_conversation_mutes_conversation_id", "conversation_mutes", ["conversation_id"])

    msg_type = sa.Enum(
        "text", "voice", "image", "video", "file", "sticker", "location", name="messagetype"
    )
    op.create_table(
        "messages",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("conversation_id", GUID, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", msg_type, nullable=False, server_default="text"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("client_id", sa.String(64)),
        sa.Column("attachment_url", sa.String(1024)),
        sa.Column("attachment_meta", postgresql.JSONB()),
        sa.Column("reply_to_id", GUID, sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("forwarded_from_id", GUID, sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index("ix_messages_reply_to_id", "messages", ["reply_to_id"])
    op.create_index("ix_messages_client_id", "messages", ["client_id"])
    op.create_index("ix_messages_conv_created", "messages", ["conversation_id", "created_at"])
    op.create_unique_constraint(
        "uq_message_conv_client", "messages", ["conversation_id", "client_id"]
    )

    op.create_table(
        "message_reactions",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("message_id", GUID, sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", "user_id", name="uq_reaction_msg_user"),
    )
    op.create_index("ix_message_reactions_message_id", "message_reactions", ["message_id"])

    receipt_state = sa.Enum("delivered", "read", name="receiptstate")
    op.create_table(
        "message_receipts",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("message_id", GUID, sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", receipt_state, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", "user_id", name="uq_receipt_msg_user"),
    )
    op.create_index("ix_message_receipts_message_id", "message_receipts", ["message_id"])
    op.create_index("ix_message_receipts_user_id", "message_receipts", ["user_id"])

    op.create_table(
        "devices",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("device_label", sa.String(120)),
        sa.Column("registration_id", sa.BigInteger(), nullable=False),
        sa.Column("identity_public_key", sa.String(255), nullable=False),
        sa.Column("identity_signing_key", sa.String(255), nullable=False),
        sa.Column("signed_prekey_id", sa.Integer(), nullable=False),
        sa.Column("signed_prekey", sa.String(255), nullable=False),
        sa.Column("prekey_signature", sa.String(512), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "device_id", name="uq_device_user_devid"),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])

    op.create_table(
        "one_time_prekeys",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("device_pk", GUID, sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.String(255), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("device_pk", "key_id", name="uq_otpk_device_keyid"),
    )
    op.create_index("ix_one_time_prekeys_device_pk", "one_time_prekeys", ["device_pk"])
    op.create_index("ix_one_time_prekeys_consumed", "one_time_prekeys", ["consumed"])

    op.create_table(
        "device_tokens",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False, unique=True),
        sa.Column("platform", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_index("ix_device_tokens_token", "device_tokens", ["token"])

    call_type = sa.Enum("voice", "video", name="calltype")
    call_dir = sa.Enum("incoming", "outgoing", "missed", name="calldirection")
    op.create_table(
        "call_logs",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("caller_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("callee_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("call_type", call_type, nullable=False),
        sa.Column("direction", call_dir, nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_call_logs_caller_id", "call_logs", ["caller_id"])
    op.create_index("ix_call_logs_callee_id", "call_logs", ["callee_id"])


def downgrade() -> None:
    for table in (
        "call_logs",
        "device_tokens",
        "one_time_prekeys",
        "devices",
        "message_receipts",
        "message_reactions",
        "messages",
        "conversation_mutes",
        "conversation_requests",
        "conversations",
        "user_blocks",
        "user_contacts",
        "otp_challenges",
        "refresh_tokens",
        "users",
    ):
        op.drop_table(table)
    for enum_name in (
        "calldirection",
        "calltype",
        "receiptstate",
        "messagetype",
        "requeststatus",
        "otppurpose",
        "otpchannel",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
