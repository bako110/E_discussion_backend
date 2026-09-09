"""Router devices / E2E keys — distribution des cles publiques Signal."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.device import (
    AddPreKeysIn,
    DeviceOut,
    KeysCountOut,
    PreKeyBundleOut,
    PushTokenIn,
    RegisterKeysIn,
)
from app.services import device_service

router = APIRouter()


@router.post("/keys", response_model=Message, status_code=status.HTTP_201_CREATED)
async def register_keys(body: RegisterKeysIn, current_user: CurrentUser, db: DbSession):
    await device_service.register_keys(db, current_user.id, body)
    return Message(message="registered")


@router.post("/keys/one-time-prekeys", response_model=Message)
async def add_prekeys(body: AddPreKeysIn, current_user: CurrentUser, db: DbSession):
    n = await device_service.add_prekeys(db, current_user.id, body)
    return Message(message=f"{n} prekeys added")


@router.get("/me/keys-count", response_model=list[KeysCountOut])
async def my_keys_count(current_user: CurrentUser, db: DbSession):
    return await device_service.keys_count(db, current_user.id)


@router.get("/me", response_model=list[DeviceOut])
async def my_devices(
    current_user: CurrentUser,
    db: DbSession,
    x_device_id: str | None = Header(None),
):
    """Liste des appareils liés au compte (« Appareils liés » dans les
    réglages). L'appareil courant est marqué via l'en-tête `X-Device-Id`."""
    return await device_service.list_devices(db, current_user.id, x_device_id)


@router.put("/push-token", response_model=Message)
async def set_push_token(body: PushTokenIn, current_user: CurrentUser, db: DbSession):
    """Enregistre le jeton de push natif de cet appareil (notifications de
    messages + réveil d'appel quand l'app est en arrière-plan/fermée)."""
    await device_service.register_push_token(db, current_user.id, body)
    return Message(message="registered")


@router.delete("/push-token", response_model=Message)
async def delete_push_token(body: PushTokenIn, current_user: CurrentUser, db: DbSession):
    await device_service.unregister_push_token(db, current_user.id, body.token)
    return Message(message="removed")


@router.get("/{user_id}/bundles", response_model=list[PreKeyBundleOut])
async def get_bundles(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Recupere un bundle X3DH par appareil actif du destinataire.
    Consomme une one-time prekey par appareil."""
    return await device_service.get_bundles(db, user_id)


@router.delete("/{device_id}/keys", response_model=Message)
async def revoke(device_id: str, current_user: CurrentUser, db: DbSession):
    await device_service.revoke_device(db, current_user.id, device_id)
    return Message(message="revoked")
