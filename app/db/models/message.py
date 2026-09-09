"""Messages + reactions + accuses de reception.

`body` contient soit le texte en clair, soit — si `encrypted=True` — le blob
JSON chiffre (payload Double Ratchet serialise). Le backend ne dechiffre
jamais : il stocke et relaie tel quel.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB


class MessageType(str, enum.Enum):
    text = "text"
    voice = "voice"
    image = "image"
    video = "video"
    file = "file"
    sticker = "sticker"
    location = "location"


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_id", name="uq_message_conv_client"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    type: Mapped[MessageType] = mapped_column(
        Enum(MessageType), default=MessageType.text, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Idempotence offline (voir MessageCreate.client_id) — unique par
    # conversation via l'index partiel ci-dessous.
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)

    attachment_url: Mapped[str | None] = mapped_column(String(1024))
    attachment_meta: Mapped[dict | None] = mapped_column(JSONB)

    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("messages.id", ondelete="SET NULL"),
        index=True,
    )
    # renseigne si ce message est une reponse a une story (affiche "a repondu
    # a votre story" + une vignette). La story peut avoir expire entre-temps.
    story_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("stories.id", ondelete="SET NULL"),
        index=True,
    )
    forwarded_from_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("messages.id", ondelete="SET NULL"),
    )

    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageReaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_reaction_msg_user"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)


class ReceiptState(str, enum.Enum):
    delivered = "delivered"
    read = "read"


class MessageReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Un accuse par (message, destinataire). En 1-to-1 il n'y a qu'un
    destinataire, mais la structure reste prete pour les groupes."""

    __tablename__ = "message_receipts"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_receipt_msg_user"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    state: Mapped[ReceiptState] = mapped_column(Enum(ReceiptState), nullable=False)
