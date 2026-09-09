"""Conversations 1-to-1 — creation/recuperation, demandes, sourdine, resume."""
from __future__ import annotations

import uuid

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db.models.conversation import (
    Conversation,
    ConversationMute,
    ConversationRequest,
    RequestStatus,
)
from app.db.models.message import Message, MessageReceipt, MessageType, ReceiptState
from app.db.models.user import User
from app.schemas.conversation import ConversationDetail, ConversationSummary
from app.services import user_service
from app.services.user_service import serialize_public
from app.services.ws_manager import manager


async def _partner_of(conv: Conversation, me_id: uuid.UUID) -> uuid.UUID:
    return conv.user_b_id if conv.user_a_id == me_id else conv.user_a_id


async def get_or_create(db: AsyncSession, me: User, partner_id: uuid.UUID) -> Conversation:
    if partner_id == me.id:
        raise AppError("conversation.cannot_message_self", status_code=400, code="message_self")
    await user_service.get_user_or_404(db, partner_id)
    if await user_service.is_blocked_between(db, me.id, partner_id):
        raise ForbiddenError("conversation.blocked", code="blocked")

    a_id, b_id = Conversation.order_pair(me.id, partner_id)
    res = await db.execute(
        select(Conversation).where(
            Conversation.user_a_id == a_id, Conversation.user_b_id == b_id
        )
    )
    conv = res.scalar_one_or_none()
    if conv is None:
        conv = Conversation(user_a_id=a_id, user_b_id=b_id)
        db.add(conv)
        await db.flush()
        # premiere prise de contact -> demande en attente
        db.add(
            ConversationRequest(
                requester_id=me.id, target_id=partner_id, status=RequestStatus.pending
            )
        )
        await db.flush()
    return conv


async def get_owned(db: AsyncSession, me: User, conversation_id: uuid.UUID) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or me.id not in (conv.user_a_id, conv.user_b_id):
        raise NotFoundError("conversation.not_found", code="conversation_not_found")
    return conv


async def request_status(db: AsyncSession, me_id: uuid.UUID, partner_id: uuid.UUID) -> str:
    res = await db.execute(
        select(ConversationRequest).where(
            or_(
                and_(
                    ConversationRequest.requester_id == me_id,
                    ConversationRequest.target_id == partner_id,
                ),
                and_(
                    ConversationRequest.requester_id == partner_id,
                    ConversationRequest.target_id == me_id,
                ),
            )
        )
    )
    req = res.scalar_one_or_none()
    if req is None or req.status == RequestStatus.accepted:
        return "accepted"
    if req.status == RequestStatus.declined:
        return "declined"
    return "pending_outgoing" if req.requester_id == me_id else "pending_incoming"


async def accept_request(db: AsyncSession, me: User, partner_id: uuid.UUID) -> None:
    """Idempotent : rejouable depuis l'outbox sans erreur."""
    res = await db.execute(
        select(ConversationRequest).where(
            ConversationRequest.requester_id == partner_id,
            ConversationRequest.target_id == me.id,
        )
    )
    req = res.scalar_one_or_none()
    if req is None:
        # deja accepte (plus de ligne pending) ou aucune demande -> no-op
        return
    if req.status != RequestStatus.accepted:
        req.status = RequestStatus.accepted
        await db.flush()
        # notifie l'initiateur que sa demande est acceptee
        await manager.send_to_user(
            str(partner_id),
            {"type": "conversation.accepted", "user_id": str(me.id)},
        )


async def decline_request(db: AsyncSession, me: User, partner_id: uuid.UUID) -> None:
    res = await db.execute(
        select(ConversationRequest).where(
            ConversationRequest.requester_id == partner_id,
            ConversationRequest.target_id == me.id,
        )
    )
    req = res.scalar_one_or_none()
    if req and req.status != RequestStatus.declined:
        req.status = RequestStatus.declined
        await db.flush()


async def set_mute(db: AsyncSession, me: User, conversation_id: uuid.UUID, muted: bool) -> None:
    await get_owned(db, me, conversation_id)
    res = await db.execute(
        select(ConversationMute).where(
            ConversationMute.user_id == me.id,
            ConversationMute.conversation_id == conversation_id,
        )
    )
    row = res.scalar_one_or_none()
    if muted and row is None:
        db.add(ConversationMute(user_id=me.id, conversation_id=conversation_id))
    elif not muted and row is not None:
        await db.delete(row)
    await db.flush()


async def is_muted(db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
    res = await db.execute(
        select(ConversationMute.id).where(
            ConversationMute.user_id == user_id,
            ConversationMute.conversation_id == conversation_id,
        )
    )
    return res.first() is not None


async def list_summaries(db: AsyncSession, me: User) -> list[ConversationSummary]:
    res = await db.execute(
        select(Conversation).where(
            or_(Conversation.user_a_id == me.id, Conversation.user_b_id == me.id)
        )
    )
    convs = sorted(
        res.scalars().all(),
        key=lambda c: c.last_message_at or c.created_at,
        reverse=True,
    )
    if not convs:
        return []

    partner_ids = [await _partner_of(c, me.id) for c in convs]
    partners = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(partner_ids)))
        ).scalars().all()
    }

    # dernier message par conversation
    last_msgs: dict[uuid.UUID, Message] = {}
    for c in convs:
        r = await db.execute(
            select(Message)
            .where(Message.conversation_id == c.id, Message.deleted_at.is_(None))
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        m = r.scalar_one_or_none()
        if m:
            last_msgs[c.id] = m

    # non-lus : messages recus sans receipt 'read'
    unread_counts: dict[uuid.UUID, int] = {}
    for c in convs:
        r = await db.execute(
            select(func.count(Message.id))
            .select_from(Message)
            .outerjoin(
                MessageReceipt,
                and_(
                    MessageReceipt.message_id == Message.id,
                    MessageReceipt.user_id == me.id,
                    MessageReceipt.state == ReceiptState.read,
                ),
            )
            .where(
                Message.conversation_id == c.id,
                Message.sender_id != me.id,
                Message.deleted_at.is_(None),
                MessageReceipt.id.is_(None),
            )
        )
        unread_counts[c.id] = int(r.scalar_one())

    out: list[ConversationSummary] = []
    for c in convs:
        pid = await _partner_of(c, me.id)
        partner = partners.get(pid)
        if partner is None:
            continue
        m = last_msgs.get(c.id)
        out.append(
            ConversationSummary(
                id=c.id,
                partner=await serialize_public(partner),
                last_message=(None if (m and m.encrypted) else (m.body if m else None)),
                last_message_type=(m.type if m else None),
                last_message_at=c.last_message_at,
                last_message_encrypted=bool(m and m.encrypted),
                unread_count=unread_counts.get(c.id, 0),
                muted=await is_muted(db, me.id, c.id),
                request_status=await request_status(db, me.id, pid),
            )
        )
    return out


async def detail(db: AsyncSession, me: User, conversation_id: uuid.UUID) -> ConversationDetail:
    conv = await get_owned(db, me, conversation_id)
    pid = await _partner_of(conv, me.id)
    partner = await user_service.get_user_or_404(db, pid)
    return ConversationDetail(
        id=conv.id,
        partner=await serialize_public(partner),
        muted=await is_muted(db, me.id, conv.id),
        request_status=await request_status(db, me.id, pid),
    )


async def clear_history(db: AsyncSession, me: User, conversation_id: uuid.UUID) -> int:
    """« Effacer la discussion » — supprime tous les messages de la
    conversation (et leurs reçus/réactions par cascade). 1-to-1 : c'est
    définitif pour les deux ; on prévient le partenaire.
    """
    conv = await get_owned(db, me, conversation_id)
    rows = (
        await db.execute(select(Message.id).where(Message.conversation_id == conv.id))
    ).scalars().all()
    n = len(rows)
    if n:
        await db.execute(
            Message.__table__.delete().where(Message.conversation_id == conv.id)
        )
        conv.last_message_at = None
    await db.flush()
    pid = await _partner_of(conv, me.id)
    await manager.send_to_user(
        str(pid),
        {"type": "conversation.cleared", "conversation_id": str(conv.id), "by": str(me.id)},
    )
    return n


async def list_media(
    db: AsyncSession, me: User, conversation_id: uuid.UUID, *, offset: int, limit: int
) -> list[dict]:
    """Médias partagés dans la conversation (images / vidéos / fichiers /
    audio), du plus récent au plus ancien."""
    conv = await get_owned(db, me, conversation_id)
    media_types = (
        MessageType.image,
        MessageType.video,
        MessageType.file,
        MessageType.voice,
    )
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.type.in_(media_types),
                Message.attachment_url.is_not(None),
                Message.deleted_at.is_(None),
            )
            .order_by(desc(Message.created_at))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "message_id": str(m.id),
            "type": m.type.value,
            "url": m.attachment_url,
            "meta": m.attachment_meta,
            "sender_id": str(m.sender_id),
            "created_at": m.created_at,
        }
        for m in rows
    ]
