"""E2EE — enregistrement des cles publiques et distribution des bundles X3DH.

Portage du service `devices` de stream_mobile. Le backend ne voit que des
cles publiques ; il consomme une one-time prekey a chaque `get_bundle`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.device import Device, OneTimePreKey
from app.db.models.push import DeviceToken
from app.schemas.device import (
    AddPreKeysIn,
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

    for otpk in data.one_time_prekeys:
        db.add(
            OneTimePreKey(device_pk=device.id, key_id=otpk.key_id, public_key=otpk.public_key)
        )
    await db.flush()
    return device


async def add_prekeys(db: AsyncSession, user_id: uuid.UUID, data: AddPreKeysIn) -> int:
    res = await db.execute(
        select(Device).where(Device.user_id == user_id, Device.device_id == data.device_id)
    )
    device = res.scalar_one_or_none()
    if device is None:
        raise NotFoundError("errors.not_found", code="device_not_found")
    for otpk in data.one_time_prekeys:
        db.add(
            OneTimePreKey(device_pk=device.id, key_id=otpk.key_id, public_key=otpk.public_key)
        )
    await db.flush()
    return len(data.one_time_prekeys)


async def keys_count(db: AsyncSession, user_id: uuid.UUID) -> list[KeysCountOut]:
    res = await db.execute(select(Device).where(Device.user_id == user_id, Device.revoked.is_(False)))
    out: list[KeysCountOut] = []
    for device in res.scalars().all():
        cnt = await db.execute(
            select(func.count(OneTimePreKey.id)).where(
                OneTimePreKey.device_pk == device.id, OneTimePreKey.consumed.is_(False)
            )
        )
        out.append(
            KeysCountOut(device_id=device.device_id, remaining_one_time_prekeys=int(cnt.scalar_one()))
        )
    return out


async def get_bundles(db: AsyncSession, target_user_id: uuid.UUID) -> list[PreKeyBundleOut]:
    """Un bundle par appareil actif du destinataire. Consomme une OTPK par
    appareil si disponible (sinon bundle sans OTPK — X3DH degrade)."""
    res = await db.execute(
        select(Device).where(Device.user_id == target_user_id, Device.revoked.is_(False))
    )
    devices = res.scalars().all()
    if not devices:
        raise NotFoundError("errors.not_found", code="no_device")

    bundles: list[PreKeyBundleOut] = []
    for device in devices:
        otpk_res = await db.execute(
            select(OneTimePreKey)
            .where(OneTimePreKey.device_pk == device.id, OneTimePreKey.consumed.is_(False))
            .order_by(OneTimePreKey.key_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        otpk = otpk_res.scalar_one_or_none()
        if otpk:
            otpk.consumed = True
        bundles.append(
            PreKeyBundleOut(
                device_id=device.device_id,
                registration_id=device.registration_id,
                identity_public_key=device.identity_public_key,
                identity_signing_key=device.identity_signing_key,
                signed_prekey_id=device.signed_prekey_id,
                signed_prekey=device.signed_prekey,
                prekey_signature=device.prekey_signature,
                one_time_prekey_id=otpk.key_id if otpk else None,
                one_time_prekey=otpk.public_key if otpk else None,
            )
        )
    await db.flush()
    return bundles


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
        cnt = await db.scalar(
            select(func.count(OneTimePreKey.id)).where(
                OneTimePreKey.device_pk == device.id, OneTimePreKey.consumed.is_(False)
            )
        )
        item = DeviceOut.model_validate(device)
        item.remaining_one_time_prekeys = int(cnt or 0)
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
