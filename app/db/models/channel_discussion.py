"""Canaux de discussion liés à une chaîne (façon Telegram) — une chaîne peut
lier jusqu'à `MAX_DISCUSSION_CHANNELS` canaux de commentaires distincts
(ex: un par langue, un par sujet), remplace l'ancien `discussion_group_id`
(relation 1-vers-1, un seul canal possible)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID

MAX_DISCUSSION_CHANNELS = 5


class ChannelDiscussion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "channel_discussions"
    __table_args__ = (
        UniqueConstraint("channel_id", "discussion_group_id", name="uq_channel_discussion"),
    )

    # la CHAÎNE principale (kind='channel') qui possède ce canal de discussion
    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # le canal de discussion lui-même (aussi kind='channel') — un même canal
    # ne peut être lié qu'à UNE seule chaîne à la fois (vérifié côté service).
    discussion_group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False, unique=True
    )
