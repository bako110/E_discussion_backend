"""Schemas E2EE — enregistrement des cles publiques + recuperation de bundle."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OneTimePreKeyIn(BaseModel):
    key_id: int
    public_key: str  # base64


class RegisterKeysIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    device_label: str | None = Field(None, max_length=120)
    registration_id: int
    identity_public_key: str
    identity_signing_key: str
    signed_prekey_id: int
    signed_prekey: str
    prekey_signature: str
    one_time_prekeys: list[OneTimePreKeyIn] = Field(default_factory=list)


class AddPreKeysIn(BaseModel):
    device_id: str
    one_time_prekeys: list[OneTimePreKeyIn]


class KeysCountOut(BaseModel):
    device_id: str
    remaining_one_time_prekeys: int


class DeviceOut(ORMModel):
    """Un appareil lié au compte (vue « Appareils liés » des réglages)."""

    device_id: str
    device_label: str | None = None
    registration_id: int
    revoked: bool = False
    created_at: datetime
    updated_at: datetime
    remaining_one_time_prekeys: int = 0
    # true si c'est l'appareil qui fait la requête (transmis via en-tête)
    is_current: bool = False


class PushTokenIn(BaseModel):
    """Jeton de push natif (FCM Android / APNs iOS) de l'appareil courant."""

    token: str = Field(..., max_length=512)
    platform: str | None = Field(None, pattern="^(ios|android)$")


class PreKeyBundleOut(BaseModel):
    device_id: str
    registration_id: int
    identity_public_key: str
    identity_signing_key: str
    signed_prekey_id: int
    signed_prekey: str
    prekey_signature: str
    one_time_prekey_id: int | None = None
    one_time_prekey: str | None = None
