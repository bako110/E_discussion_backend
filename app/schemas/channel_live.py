"""Schemas diffusion en direct d'une chaîne (LiveKit self-hosted)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.channel_live import ChannelLiveStatus
from app.schemas.common import ORMModel


class ChannelLiveStartIn(BaseModel):
    title: str | None = Field(None, max_length=120)


class ChannelLiveOut(ORMModel):
    id: uuid.UUID
    group_id: uuid.UUID
    started_by: uuid.UUID
    status: ChannelLiveStatus
    room_name: str
    title: str | None = None
    peak_viewers: int = 0
    started_at: datetime
    ended_at: datetime | None = None
    # infos chaîne utiles à l'affichage dans la liste "chaînes en direct"
    channel_name: str | None = None
    channel_avatar_url: str | None = None
    subscriber_count: int = 0


class ChannelLiveStartOut(ChannelLiveOut):
    """Réponse au démarrage : inclut l'accès LiveKit pour le diffuseur (admin)."""

    livekit_url: str
    token: str


class ChannelLiveJoinOut(BaseModel):
    """Réponse à la jonction d'un spectateur : accès LiveKit en LECTURE SEULE."""

    livekit_url: str
    token: str
    room_name: str
    channel_live: ChannelLiveOut
