"""Diffusion en direct d'une chaîne (LiveKit self-hosted, façon YouTube/Insta
Live) — un admin de la chaîne démarre/arrête ; les abonnés rejoignent en
spectateurs (audio+vidéo en lecture seule, pas de publication).

Une seule session « live » à la fois par chaîne (contrainte applicative,
voir `channel_live_service.start`) — pas de multi-stream simultané pour une
même chaîne dans cette V1.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ChannelLiveStatus(str, enum.Enum):
    live = "live"
    ended = "ended"


class ChannelLive(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "channel_lives"

    group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    started_by: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ChannelLiveStatus] = mapped_column(
        Enum(ChannelLiveStatus), default=ChannelLiveStatus.live, nullable=False
    )
    # nom de la room LiveKit (unique par session live)
    room_name: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))

    # pic de spectateurs simultanés — mis à jour au best-effort depuis les
    # webhooks LiveKit (participant_joined/left), affiché à l'audience.
    peak_viewers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
