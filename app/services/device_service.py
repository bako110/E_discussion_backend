"""E2EE — enregistrement des cles publiques et distribution des bundles X3DH.

Pas de one-time prekeys : X3DH tolere nativement leur absence (3 DH au lieu
de 4, voir crypto/x3dh.ts cote client) — la gestion d'un stock d'OTPK par
appareil (generation, reapprovisionnement, consommation, cascade de
bootstrap "avec/sans OTPK") s'est averee etre la principale source de
sessions incoherentes en usage reel. La table `one_time_prekeys` reste en
base (colonnes deja migrees) mais n'est plus alimentee ni lue.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.device import Device
from app.db.models.push import DeviceToken
from app.schemas.device import (
    DeviceOut,
    KeysCountOut,
    PreKeyBundleOut,
    PushTokenIn,
    RegisterKeysIn,
)


async def register_keys(db: AsyncSession, user_id: uuid.UUID, data: RegisterKeysIn) -> Device:
    res = await db.execute(
        select(Device).where(Device.user_id == user_id, Device.device_id == data.device_id)
    )
    device = res.scalar_one_or_none()
    if device is None:
        device = Device(user_id=user_id, device_id=data.device_id)
        db.add(device)

    device.device_label = data.device_label
    device.registration_id = data.registration_id
    device.identity_public_key = data.identity_public_key
    device.identity_signing_key = data.identity_signing_key
    device.signed_prekey_id = data.signed_prekey_id
    device.signed_prekey = data.signed_prekey
    device.prekey_signature = data.prekey_signature
    device.revoked = False
    await db.flush()

    # Modele SINGLE-DEVICE (Phase 1) : un seul appareil actif par compte.
    # Quand un appareil s'enregistre (reinstall, changement de tel...), on
    # revoque tous les AUTRES — sinon `bundles()` pourrait servir le bundle
    # d'un ancien appareil dont le pair n'a plus les cles privees -> messages
    # a jamais indechiffrables.
    others = (
        await db.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.id != device.id,
                Device.revoked.is_(False),
            )
        )
    ).scalars().all()
    for old in others:
        old.revoked = True

    await db.flush()
    return device


async def keys_count(db: AsyncSession, user_id: uuid.UUID) -> list[KeysCountOut]:
    """Conserve pour compat API (l'ecran « Appareils lies » l'affiche encore) —
    toujours 0 desormais, plus d'OTPK a compter."""
    res = await db.execute(select(Device).where(Device.user_id == user_id, Device.revoked.is_(False)))
    return [KeysCountOut(device_id=d.device_id, remaining_one_time_prekeys=0) for d in res.scalars().all()]


async def get_bundles(db: AsyncSession, target_user_id: uuid.UUID) -> list[PreKeyBundleOut]:
    """Bundle(s) de l'appareil actif du destinataire. Modele single-device :
    on renvoie le PLUS RECENT en premier (le client n'utilise que `[0]`)."""
    res = await db.execute(
        select(Device)
        .where(Device.user_id == target_user_id, Device.revoked.is_(False))
        .order_by(Device.updated_at.desc(), Device.created_at.desc())
    )
    devices = res.scalars().all()
    if not devices:
        raise NotFoundError("errors.not_found", code="no_device")

    return [
        PreKeyBundleOut(
            device_id=device.device_id,
            registration_id=device.registration_id,
            identity_public_key=device.identity_public_key,
            identity_signing_key=device.identity_signing_key,
            signed_prekey_id=device.signed_prekey_id,
            signed_prekey=device.signed_prekey,
            prekey_signature=device.prekey_signature,
            one_time_prekey_id=None,
            one_time_prekey=None,
        )
        for device in devices
    ]


async def list_devices(
    db: AsyncSession, user_id: uuid.UUID, current_device_id: str | None = None
) -> list[DeviceOut]:
    """Tous les appareils liés au compte (révoqués inclus) pour l'écran
    « Appareils liés »."""
    res = await db.execute(
        select(Device).where(Device.user_id == user_id).order_by(Device.created_at)
    )
    out: list[DeviceOut] = []
    for device in res.scalars().all():
        item = DeviceOut.model_validate(device)
        item.remaining_one_time_prekeys = 0
        item.is_current = bool(current_device_id) and device.device_id == current_device_id
        out.append(item)
    return out


# ── Jetons de push (notifications natives : messages + appels) ──────────────
async def register_push_token(
    db: AsyncSession, user_id: uuid.UUID, data: PushTokenIn
) -> None:
    """Enregistre (ou réassigne) un jeton de push pour l'utilisateur courant.

    Un même jeton ne peut appartenir qu'à un compte : s'il existait pour un
    autre utilisateur (appareil partagé, changement de compte), on le
    ré-attribue.
    """
    row = (
        await db.execute(select(DeviceToken).where(DeviceToken.token == data.token))
    ).scalar_one_or_none()
    if row is None:
        db.add(DeviceToken(user_id=user_id, token=data.token, platform=data.platform))
    else:
        row.user_id = user_id
        row.platform = data.platform or row.platform
    await db.flush()


async def unregister_push_token(db: AsyncSession, user_id: uuid.UUID, token: str) -> None:
    row = (
        await db.execute(
            select(DeviceToken).where(
                DeviceToken.token == token, DeviceToken.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()


async def revoke_device(db: AsyncSession, user_id: uuid.UUID, device_id: str) -> None:
    res = await db.execute(
        select(Device).where(Device.user_id == user_id, Device.device_id == device_id)
    )
    device = res.scalar_one_or_none()
    if device is None:
        raise NotFoundError("errors.not_found", code="device_not_found")
    device.revoked = True
    await db.flush()
