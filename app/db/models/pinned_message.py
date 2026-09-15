"""Message épinglé — façon WhatsApp : jusqu'à 3 messages épinglés en même
temps par conversation/groupe, affichés en haut du chat.

Un seul type couvre les deux contextes (1-1 et groupe) : `conversation_id`
XOR `group_id` est renseigné selon l'origine du message épinglé (jamais les
deux). Qui peut épingler est vérifié côté service, pas ici :
  - 1-1 : les deux participants ;
  - groupe : owner/admin uniquement (comme WhatsApp).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class PinnedMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pinned_messages"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_pinned_message"),
    )

    # exactement un des deux est renseigné (jamais les deux, jamais aucun) —
    # vérifié côté service à la création.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    # message CONVERSATION (1-1) ou GROUP_MESSAGE (groupe) selon le contexte —
    # pas de FK stricte : les deux tables de messages sont distinctes, on ne
    # peut pas pointer une seule colonne vers l'une ou l'autre proprement.
    message_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    pinned_by: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # null = épinglé indéfiniment. Sinon, désépinglé automatiquement (lecture
    # paresseuse — voir pinned_message_service._purge_expired) à cette date.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
