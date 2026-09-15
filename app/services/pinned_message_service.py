"""Messages épinglés — 1-1 (les deux participants) et groupe/chaîne
(owner/admin uniquement, comme WhatsApp). Jusqu'à 3 épinglés en même temps
par conversation/groupe — épingler un 4e échoue tant qu'on n'en a pas
désépinglé un (l'appelant choisit explicitement lequel, pas de "dernier
entré, premier sorti" implicite qui surprendrait l'utilisateur).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db.models.conversation import Conversation
from app.db.models.group import Group, GroupMember, GroupRole
from app.db.models.group import GroupMessage as GroupMessageModel
from app.db.models.message import Message
from app.db.models.pinned_message import PinnedMessage
from app.db.models.user import User
from app.schemas.pinned_message import (
    PinnedMessageOut,
    PinnedMessagePreview,
)
from app.services import conversation_service
from app.services.ws_manager import manager

_MAX_PINNED = 3
_ADMIN_ROLES = {GroupRole.owner, GroupRole.admin}


async def _serialize(db: AsyncSession, pin: PinnedMessage) -> PinnedMessageOut:
    out = PinnedMessageOut.model_validate(pin)
    if pin.conversation_id:
        msg = await db.get(Message, pin.message_id)
        if msg is not None:
            out.message = PinnedMessagePreview(
                id=msg.id, type=msg.type.value, body=msg.body, sender_id=msg.sender_id
            )
    else:
        gmsg = await db.get(GroupMessageModel, pin.message_id)
        if gmsg is not None:
            out.message = PinnedMessagePreview(
                id=gmsg.id, type=gmsg.type, body=gmsg.body, sender_id=gmsg.sender_id
            )
    return out


# ── 1-1 ──────────────────────────────────────────────────────────────────
async def list_conversation(
    db: AsyncSession, me: User, conversation_id: uuid.UUID
) -> list[PinnedMessageOut]:
    await conversation_service.get_owned(db, me, conversation_id)
    rows = (
        await db.execute(
            select(PinnedMessage)
            .where(PinnedMessage.conversation_id == conversation_id)
            .order_by(PinnedMessage.created_at.desc())
        )
    ).scalars().all()
    return [await _serialize(db, p) for p in rows]


async def pin_conversation_message(
    db: AsyncSession, me: User, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> PinnedMessageOut:
    conv = await conversation_service.get_owned(db, me, conversation_id)
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conv.id or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")

    existing = await db.scalar(
        select(PinnedMessage).where(PinnedMessage.message_id == message_id)
    )
    if existing is not None:
        return await _serialize(db, existing)

    current = (
        await db.execute(
            select(PinnedMessage).where(PinnedMessage.conversation_id == conversation_id)
        )
    ).scalars().all()
    if len(current) >= _MAX_PINNED:
        raise AppError(
            "pin.limit_reached", status_code=409, code="pin_limit_reached"
        )

    pin = PinnedMessage(
        conversation_id=conversation_id, message_id=message_id, pinned_by=me.id
    )
    db.add(pin)
    await db.flush()

    partner_id = conv.user_b_id if conv.user_a_id == me.id else conv.user_a_id
    await manager.send_to_user(
        str(partner_id),
        {
            "type": "message.pinned",
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        },
    )
    return await _serialize(db, pin)


async def unpin_conversation_message(
    db: AsyncSession, me: User, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    conv = await conversation_service.get_owned(db, me, conversation_id)
    pin = await db.scalar(
        select(PinnedMessage).where(
            PinnedMessage.conversation_id == conversation_id,
            PinnedMessage.message_id == message_id,
        )
    )
    if pin is None:
        raise NotFoundError("pin.not_found", code="pin_not_found")
    await db.delete(pin)
    await db.flush()

    partner_id = conv.user_b_id if conv.user_a_id == me.id else conv.user_a_id
    await manager.send_to_user(
        str(partner_id),
        {
            "type": "message.unpinned",
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        },
    )


# ── groupe / chaîne ────────────────────────────────────────────────────────
async def _require_group_admin(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise NotFoundError("group.not_found", code="group_not_found")
    mem = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )
    if mem is None:
        raise ForbiddenError("group.not_member", code="not_member")
    if mem.role not in _ADMIN_ROLES:
        raise ForbiddenError("group.admin_only", code="admin_only")
    return group


async def list_group(
    db: AsyncSession, me: User, group_id: uuid.UUID
) -> list[PinnedMessageOut]:
    mem = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == me.id
        )
    )
    if mem is None:
        raise ForbiddenError("group.not_member", code="not_member")
    rows = (
        await db.execute(
            select(PinnedMessage)
            .where(PinnedMessage.group_id == group_id)
            .order_by(PinnedMessage.created_at.desc())
        )
    ).scalars().all()
    return [await _serialize(db, p) for p in rows]


async def pin_group_message(
    db: AsyncSession, me: User, group_id: uuid.UUID, message_id: uuid.UUID
) -> PinnedMessageOut:
    await _require_group_admin(db, group_id, me.id)
    gmsg = await db.get(GroupMessageModel, message_id)
    if gmsg is None or gmsg.group_id != group_id or gmsg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")

    existing = await db.scalar(
        select(PinnedMessage).where(PinnedMessage.message_id == message_id)
    )
    if existing is not None:
        return await _serialize(db, existing)

    current = (
        await db.execute(select(PinnedMessage).where(PinnedMessage.group_id == group_id))
    ).scalars().all()
    if len(current) >= _MAX_PINNED:
        raise AppError("pin.limit_reached", status_code=409, code="pin_limit_reached")

    pin = PinnedMessage(group_id=group_id, message_id=message_id, pinned_by=me.id)
    db.add(pin)
    await db.flush()

    rows = await db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    for (uid,) in rows.all():
        if uid == me.id:
            continue
        await manager.send_to_user(
            str(uid),
            {
                "type": "group.message.pinned",
                "group_id": str(group_id),
                "message_id": str(message_id),
            },
        )
    return await _serialize(db, pin)


async def unpin_group_message(
    db: AsyncSession, me: User, group_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    await _require_group_admin(db, group_id, me.id)
    pin = await db.scalar(
        select(PinnedMessage).where(
            PinnedMessage.group_id == group_id, PinnedMessage.message_id == message_id
        )
    )
    if pin is None:
        raise NotFoundError("pin.not_found", code="pin_not_found")
    await db.delete(pin)
    await db.flush()

    rows = await db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    for (uid,) in rows.all():
        await manager.send_to_user(
            str(uid),
            {
                "type": "group.message.unpinned",
                "group_id": str(group_id),
                "message_id": str(message_id),
            },
        )
