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
    # parametres de confidentialite (visibles uniquement par soi). Les modes
    # 'everyone_except' / 'only' ont une liste par champ servie par
    # GET /users/me/privacy.
    last_seen_privacy: str = "everyone"
    profile_photo_privacy: str = "everyone"
    about_privacy: str = "everyone"
    online_privacy: str = "match_last_seen"
    # confidentialite des statuts (la liste est servie par GET /stories/audience)
    story_audience_mode: str = "contacts"
    read_receipts: bool = True
    # preferences d'appel (synchronisees entre appareils)
    call_ringtone: str = "default"
    call_vibrate: bool = True
    call_answer_on_speaker: bool = False
    call_low_data: bool = False
    call_block_unknown: bool = False


_RINGTONE = r"^(default|classic|soft)$"


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
    call_ringtone: str | None = Field(None, pattern=_RINGTONE)
    call_vibrate: bool | None = None
    call_answer_on_speaker: bool | None = None
    call_low_data: bool | None = None
    call_block_unknown: bool | None = None


class PrivacyFieldOut(BaseModel):
    mode: str
    contact_ids: list[uuid.UUID] = Field(default_factory=list)


class PrivacySettingsOut(BaseModel):
    """Etat complet de la confidentialite du profil (mode + liste par champ)."""

    online: PrivacyFieldOut
    last_seen: PrivacyFieldOut
    profile_photo: PrivacyFieldOut
    about: PrivacyFieldOut


class PrivacyFieldIn(BaseModel):
    field: str = Field(..., pattern=r"^(online|last_seen|profile_photo|about)$")
    mode: str = Field(
        ..., pattern=r"^(everyone|contacts|nobody|everyone_except|only|match_last_seen)$"
    )
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2000)


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
