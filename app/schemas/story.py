"""Schemas stories (statuts ephemeres)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.story import StoryMediaType
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


class StoryCreate(BaseModel):
    media_type: StoryMediaType = StoryMediaType.text
    media_url: str | None = Field(None, max_length=1024)
    caption: str | None = Field(None, max_length=2000)
    background_color: str | None = Field(None, max_length=16)
    font: str | None = Field(None, max_length=32)
    # borne large : l'utilisateur decoupe deja le segment cote client
    duration_sec: int = Field(5, ge=1, le=600)
    thumbnail_url: str | None = Field(None, max_length=1024)
    audio_url: str | None = Field(None, max_length=1024)
    audio_name: str | None = Field(None, max_length=120)
    audience: str = Field("everyone", pattern="^(everyone|contacts)$")


class StoryUpdate(BaseModel):
    """Modification d'une story existante (auteur uniquement)."""

    caption: str | None = Field(None, max_length=2000)
    background_color: str | None = Field(None, max_length=16)
    font: str | None = Field(None, max_length=32)
    duration_sec: int | None = Field(None, ge=1, le=600)


class StoryOut(ORMModel):
    id: uuid.UUID
    author_id: uuid.UUID
    media_type: StoryMediaType
    media_url: str | None = None
    caption: str | None = None
    background_color: str | None = None
    font: str | None = None
    duration_sec: int = 5
    thumbnail_url: str | None = None
    audio_url: str | None = None
    audio_name: str | None = None
    audience: str = "everyone"
    created_at: datetime
    expires_at: datetime
    edited_at: datetime | None = None

    # agregats calcules cote service
    view_count: int = 0
    reaction_count: int = 0
    seen_by_me: bool = False
    my_reaction: str | None = None
    is_mine: bool = False


class StoryFeedItem(BaseModel):
    """Groupe de stories d'un meme auteur (comme WhatsApp : une puce par
    personne, plusieurs stories dedans)."""

    author: UserPublic
    stories: list[StoryOut]
    has_unseen: bool = False
    latest_at: datetime


class StoryReactionIn(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=16)


class StoryReplyIn(BaseModel):
    """Reponse a une story -> devient un message dans la conversation."""

    body: str = Field(..., min_length=1, max_length=4000)
    client_id: str | None = Field(None, max_length=64)


class StoryViewerOut(ORMModel):
    user: UserPublic
    viewed_at: datetime
    reaction: str | None = None
