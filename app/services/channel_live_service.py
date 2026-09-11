"""Diffusion en direct d'une chaine (LiveKit self-hosted).

Roles de ce backend :
  - creer la room + signer les tokens JWT d'acces LiveKit (diffuseur en
    lecture/ecriture, spectateurs en lecture SEULE) ;
  - notifier tous les abonnes de la chaine au demarrage/arret (WS) ;
  - historiser la session (`channel_lives`).

Un admin (owner/admin) demarre/arrete ; un abonne (n'importe quel membre)
peut rejoindre en spectateur. Une seule session live a la fois par chaine.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db.models.channel_live import ChannelLive, ChannelLiveStatus
from app.db.models.group import Group, GroupKind, GroupMember, GroupRole
from app.db.models.user import User
from app.schemas.channel_live import (
    ChannelLiveJoinOut,
    ChannelLiveOut,
    ChannelLiveStartIn,
    ChannelLiveStartOut,
)
from app.services import livekit_service
from app.services.ws_manager import manager

_ADMIN_ROLES = {GroupRole.owner, GroupRole.admin}


def _now() -> datetime:
    return datetime.now(UTC)


async def _membership(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> GroupMember | None:
    return await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )


async def _load_channel(db: AsyncSession, group_id: uuid.UUID) -> Group:
    group = await db.get(Group, group_id)
    if group is None or group.kind != GroupKind.channel:
        raise NotFoundError("channel.not_found", code="channel_not_found")
    return group


async def _member_ids(db: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    return [r[0] for r in rows.all()]


async def _subscriber_count(db: AsyncSession, group_id: uuid.UUID) -> int:
    n = await db.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
    )
    return int(n or 0)


async def _to_out(db: AsyncSession, group: Group, live: ChannelLive) -> ChannelLiveOut:
    out = ChannelLiveOut.model_validate(live)
    out.channel_name = group.name
    out.channel_avatar_url = group.avatar_url
    out.subscriber_count = await _subscriber_count(db, group.id)
    return out


# ── demarrage (admin) ─────────────────────────────────────────────────────
async def start(
    db: AsyncSession, me: User, group_id: uuid.UUID, body: ChannelLiveStartIn
) -> ChannelLiveStartOut:
    if not settings.calls_enabled:
        raise livekit_service.CallsDisabledError()

    group = await _load_channel(db, group_id)
    mem = await _membership(db, group_id, me.id)
    if mem is None or mem.role not in _ADMIN_ROLES:
        raise ForbiddenError("channel.live.admin_only", code="live_admin_only")

    existing = await db.scalar(
        select(ChannelLive).where(
            ChannelLive.group_id == group_id, ChannelLive.status == ChannelLiveStatus.live
        )
    )
    if existing is not None:
        raise AppError(
            "channel.live.already_live", status_code=409, code="channel_already_live"
        )

    room_name = f"live_{uuid.uuid4().hex}"
    live = ChannelLive(
        group_id=group_id,
        started_by=me.id,
        status=ChannelLiveStatus.live,
        room_name=room_name,
        title=body.title,
        started_at=_now(),
    )
    db.add(live)
    await db.flush()

    token = livekit_service.build_access_token(
        room_name=room_name,
        identity=str(me.id),
        display_name=me.display_name or me.username,
        publish=True,
    )

    out = await _to_out(db, group, live)
    payload = {
        "type": "channel.live.started",
        "group_id": str(group_id),
        "live_id": str(live.id),
        "room_name": room_name,
        "title": live.title,
        "channel_name": group.name,
        "channel_avatar_url": group.avatar_url,
    }
    for uid in await _member_ids(db, group_id):
        if uid == me.id:
            continue
        await manager.send_to_user(str(uid), payload)

    return ChannelLiveStartOut(
        **out.model_dump(),
        livekit_url=settings.LIVEKIT_URL,
        token=token,
    )


# ── rejoindre (spectateur — n'importe quel abonne) ───────────────────────
async def join(db: AsyncSession, me: User, group_id: uuid.UUID) -> ChannelLiveJoinOut:
    group = await _load_channel(db, group_id)
    mem = await _membership(db, group_id, me.id)
    if mem is None:
        raise ForbiddenError("group.not_member", code="not_member")

    live = await db.scalar(
        select(ChannelLive).where(
            ChannelLive.group_id == group_id, ChannelLive.status == ChannelLiveStatus.live
        )
    )
    if live is None:
        raise NotFoundError("channel.live.not_live", code="channel_not_live")

    token = livekit_service.build_access_token(
        room_name=live.room_name,
        identity=str(me.id),
        display_name=me.display_name or me.username,
        publish=False,  # spectateur : lecture seule, jamais de publish
    )
    out = await _to_out(db, group, live)
    return ChannelLiveJoinOut(
        livekit_url=settings.LIVEKIT_URL,
        token=token,
        room_name=live.room_name,
        channel_live=out,
    )


# ── arret (admin) ─────────────────────────────────────────────────────────
async def stop(db: AsyncSession, me: User, group_id: uuid.UUID) -> ChannelLiveOut:
    group = await _load_channel(db, group_id)
    mem = await _membership(db, group_id, me.id)
    if mem is None or mem.role not in _ADMIN_ROLES:
        raise ForbiddenError("channel.live.admin_only", code="live_admin_only")

    live = await db.scalar(
        select(ChannelLive).where(
            ChannelLive.group_id == group_id, ChannelLive.status == ChannelLiveStatus.live
        )
    )
    if live is None:
        raise NotFoundError("channel.live.not_live", code="channel_not_live")

    live.status = ChannelLiveStatus.ended
    live.ended_at = _now()
    await db.flush()

    payload = {
        "type": "channel.live.ended",
        "group_id": str(group_id),
        "live_id": str(live.id),
    }
    for uid in await _member_ids(db, group_id):
        await manager.send_to_user(str(uid), payload)

    return await _to_out(db, group, live)


# ── liste des chaines actuellement en direct (annuaire) ───────────────────
async def list_live(db: AsyncSession, me: User) -> list[ChannelLiveOut]:
    """Chaines dont JE SUIS ABONNE et qui ont une session live en cours —
    façon liste « chaînes en direct » de l'écran Stories."""
    rows = (
        await db.execute(
            select(ChannelLive, Group)
            .join(Group, Group.id == ChannelLive.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(
                GroupMember.user_id == me.id,
                ChannelLive.status == ChannelLiveStatus.live,
            )
            .order_by(ChannelLive.started_at.desc())
        )
    ).all()
    return [await _to_out(db, group, live) for live, group in rows]


async def get_for_channel(db: AsyncSession, group_id: uuid.UUID) -> ChannelLiveOut | None:
    """Session live en cours pour une chaine donnee, ou None. Utilise par
    l'ecran d'info/parametres de la chaine (bouton Démarrer/Rejoindre)."""
    group = await _load_channel(db, group_id)
    live = await db.scalar(
        select(ChannelLive).where(
            ChannelLive.group_id == group_id, ChannelLive.status == ChannelLiveStatus.live
        )
    )
    if live is None:
        return None
    return await _to_out(db, group, live)
