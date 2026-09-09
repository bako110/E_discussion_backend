"""Schemas utilisateur."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserPublic(ORMModel):
    id: uuid.UUID
    username: str | None
    display_name: str | None
    avatar_url: str | None
    about: str | None
    last_seen_at: datetime | None
    is_online: bool = False  # rempli par le service depuis Redis


_PRIVACY = r"^(everyone|contacts|nobody)$"


class UserMe(UserPublic):
    email: str | None
    phone: str | None
    locale: str
    email_verified: bool
    phone_verified: bool
    # parametres de confidentialite (visibles uniquement par soi)
    last_seen_privacy: str = "everyone"
    profile_photo_privacy: str = "everyone"
    about_privacy: str = "everyone"
    read_receipts: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=80)
    username: str | None = Field(None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.]+$")
    about: str | None = Field(None, max_length=500)
    avatar_url: str | None = None
    locale: str | None = Field(None, max_length=8)
    last_seen_privacy: str | None = Field(None, pattern=_PRIVACY)
    profile_photo_privacy: str | None = Field(None, pattern=_PRIVACY)
    about_privacy: str | None = Field(None, pattern=_PRIVACY)
    read_receipts: bool | None = None


class ContactSyncIn(BaseModel):
    contacts: list[ContactEntry] = Field(default_factory=list, max_length=5000)


class ContactEntry(BaseModel):
    phone: str = Field(..., description="Numero au format E.164")
    display_name: str | None = None


class ContactMatch(ORMModel):
    phone: str
    display_name: str | None
    user: UserPublic | None


ContactSyncIn.model_rebuild()
