"""Conversation 1-to-1 + demande de conversation + mise en sourdine.

`Conversation` porte une paire ordonnee (user_a < user_b sur l'UUID) pour
garantir l'unicite : une seule conversation par paire d'utilisateurs.
Les compteurs de non-lus sont derives des `MessageReceipt`, pas stockes ici.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_conversation_pair"),
    )

    # invariant applicatif : user_a_id < user_b_id (comparaison str(UUID))
    user_a_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_b_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    @staticmethod
    def order_pair(u1: uuid.UUID, u2: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        return (u1, u2) if str(u1) < str(u2) else (u2, u1)


class RequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class ConversationRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Premier contact : tant que le destinataire n'a pas accepte, la
    conversation est en 'pending' (comme les demandes de message)."""

    __tablename__ = "conversation_requests"
    __table_args__ = (
        UniqueConstraint("requester_id", "target_id", name="uq_request_pair"),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus), default=RequestStatus.pending, nullable=False
    )


class ConversationMute(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversation_mutes"
    __table_args__ = (
        UniqueConstraint("user_id", "conversation_id", name="uq_mute_user_conv"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # null = indefini


class ConversationHide(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """« Supprimer la conversation » façon WhatsApp : masquee SEULEMENT pour
    l'utilisateur qui a supprime, jamais pour l'autre. L'historique n'est pas
    efface (voir `clear_history` pour ca). Reapparait automatiquement des
    qu'un nouveau message arrive APRES `hidden_at` (voir list_summaries)."""

    __tablename__ = "conversation_hides"
    __table_args__ = (
        UniqueConstraint("user_id", "conversation_id", name="uq_hide_user_conv"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    hidden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
