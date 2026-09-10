"""Messages — envoi, historique, edition, suppression, reactions, accuses.

Le backend ne dechiffre jamais : si `encrypted=True`, `body` est le blob
Double Ratchet serialise, stocke et relaye tel quel.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db.models.conversation import Conversation
from app.db.models.message import (
    Message,
    MessageReaction,
    MessageReceipt,
    MessageType,
    ReceiptState,
)
from app.db.models.user import User
from app.schemas.conversation import MessageCreate, MessageOut, ReplyPreview
from app.services import conversation_service, user_service
from app.services.push_service import push_to_user
from app.services.ws_manager import manager

# Fenetre d'edition tres large (demande produit : editer un message meme
# apres 24h). On garde une limite haute pour eviter la reecriture
# d'historique ancien ; `edited_at` marque toujours la modification.
_EDIT_WINDOW_SEC = 30 * 24 * 60 * 60  # 30 jours


async def _partner_id(conv: Conversation, me_id: uuid.UUID) -> uuid.UUID:
    return conv.user_b_id if conv.user_a_id == me_id else conv.user_a_id


async def _serialize(
    db: AsyncSession,
    m: Message,
    *,
    viewer_id: uuid.UUID,
    viewer_read_receipts: bool = True,
) -> MessageOut:
    reply = None
    if m.reply_to_id:
        rt = await db.get(Message, m.reply_to_id)
        if rt:
            reply = ReplyPreview(
                id=rt.id,
                type=rt.type,
                body="" if rt.encrypted else rt.body,
                sender_id=rt.sender_id,
            )

    my_reaction = None
    rr = await db.execute(
        select(MessageReaction.emoji).where(
            MessageReaction.message_id == m.id, MessageReaction.user_id == viewer_id
        )
    )
    row = rr.first()
    if row:
        my_reaction = row[0]

    delivered = read = False
    if m.sender_id == viewer_id:
        rc = await db.execute(
            select(MessageReceipt.state).where(MessageReceipt.message_id == m.id)
        )
        states = {s for (s,) in rc.all()}
        delivered = ReceiptState.delivered in states or ReceiptState.read in states
        # reciprocite WhatsApp : si J'AI desactive les accuses de lecture, je ne
        # vois pas non plus quand l'autre a lu mes messages.
        read = viewer_read_receipts and (ReceiptState.read in states)

    out = MessageOut.model_validate(m)
    out.reply_to = reply
    out.reaction = my_reaction
    out.delivered = delivered
    out.read = read
    return out


async def send(
    db: AsyncSession, me: User, conversation_id: uuid.UUID, data: MessageCreate
) -> MessageOut:
    conv = await conversation_service.get_owned(db, me, conversation_id)
    partner_id = await _partner_id(conv, me.id)

    if await user_service.is_blocked_between(db, me.id, partner_id):
        raise ForbiddenError("conversation.blocked", code="blocked")

    # demande refusee -> interdit ; en attente -> l'initiateur peut ecrire,
    # la cible non (tant qu'elle n'a pas accepte, elle ne devrait pas repondre)
    status = await conversation_service.request_status(db, me.id, partner_id)
    if status == "declined":
        raise ForbiddenError("conversation.blocked", code="request_declined")

    if data.type == MessageType.text and not data.body.strip() and not data.attachment_url:
        raise AppError("errors.validation", status_code=422, code="empty_message")

    # Idempotence : rejeu de l'outbox apres reconnexion -> renvoyer le message
    # deja cree pour ce client_id au lieu d'un doublon.
    if data.client_id:
        existing = await db.execute(
            select(Message).where(
                Message.conversation_id == conv.id, Message.client_id == data.client_id
            )
        )
        dup = existing.scalar_one_or_none()
        if dup is not None:
            return await _serialize(
                db, dup, viewer_id=me.id, viewer_read_receipts=me.read_receipts
            )

    msg = Message(
        conversation_id=conv.id,
        sender_id=me.id,
        type=data.type,
        body=data.body,
        encrypted=data.encrypted,
        attachment_url=data.attachment_url,
        attachment_meta=data.attachment_meta,
        reply_to_id=data.reply_to_id,
        forwarded_from_id=data.forwarded_from_id,
        client_id=data.client_id,
    )
    db.add(msg)
    conv.last_message_at = datetime.now(UTC)
    await db.flush()

    payload = (await _serialize(db, msg, viewer_id=partner_id)).model_dump(mode="json")
    await manager.send_to_user(str(partner_id), {"type": "message.new", "message": payload})

    if not await conversation_service.is_muted(db, partner_id, conv.id):
        # message chiffré : le serveur ne connaît pas le contenu -> aperçu générique
        preview = (
            ""
            if msg.encrypted
            else (msg.body[:120] if msg.type == MessageType.text else f"[{msg.type.value}]")
        )
        sender_name = me.display_name or me.username or "Message"
        await push_to_user(
            db,
            partner_id,
            title=sender_name,
            body=preview or "Nouveau message",
            data={
                "type": "message",
                "conversation_id": str(conv.id),
                "sender_id": str(me.id),
                "sender_name": sender_name,
                "message_id": str(msg.id),
                "encrypted": "1" if msg.encrypted else "0",
            },
        )

    return await _serialize(
        db, msg, viewer_id=me.id, viewer_read_receipts=me.read_receipts
    )


async def history(
    db: AsyncSession,
    me: User,
    conversation_id: uuid.UUID,
    *,
    offset: int,
    limit: int,
    since: datetime | None = None,
) -> list[MessageOut]:
    """Historique pagine (ordre anti-chronologique). Si `since` est fourni,
    renvoie a la place TOUS les messages crees ou modifies apres cette date
    (sync delta apres reconnexion) — messages supprimes inclus."""
    conv = await conversation_service.get_owned(db, me, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conv.id)
    if since is not None:
        stmt = stmt.where(
            (Message.created_at > since)
            | (Message.edited_at > since)
            | (Message.deleted_at > since)
        ).order_by(Message.created_at)
    else:
        stmt = stmt.order_by(desc(Message.created_at)).offset(offset).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        await _serialize(
            db, m, viewer_id=me.id, viewer_read_receipts=me.read_receipts
        )
        for m in rows
    ]


async def mark_read(db: AsyncSession, me: User, conversation_id: uuid.UUID) -> int:
    conv = await conversation_service.get_owned(db, me, conversation_id)

    # Messages du partenaire pas encore marqués "lu" par moi. On récupère aussi
    # le reçu existant éventuel (souvent "delivered") : contrainte unique
    # (message_id, user_id) -> il faut le METTRE À JOUR, pas en réinsérer un.
    rows = (
        await db.execute(
            select(Message, MessageReceipt)
            .outerjoin(
                MessageReceipt,
                and_(
                    MessageReceipt.message_id == Message.id,
                    MessageReceipt.user_id == me.id,
                ),
            )
            .where(
                Message.conversation_id == conv.id,
                Message.sender_id != me.id,
                or_(
                    MessageReceipt.id.is_(None),
                    MessageReceipt.state != ReceiptState.read,
                ),
            )
        )
    ).all()

    senders: set[uuid.UUID] = set()
    for msg, receipt in rows:
        if receipt is None:
            db.add(MessageReceipt(message_id=msg.id, user_id=me.id, state=ReceiptState.read))
        else:
            receipt.state = ReceiptState.read
        senders.add(msg.sender_id)
    await db.flush()

    # Accuses de lecture : si le lecteur les a desactives, on marque lu en
    # local (compteur de non-lus) mais on NE previent PAS l'expediteur.
    if me.read_receipts:
        for sender_id in senders:
            await manager.send_to_user(
                str(sender_id),
                {"type": "receipt.read", "conversation_id": str(conv.id), "reader_id": str(me.id)},
            )
    return len(rows)


async def mark_delivered(db: AsyncSession, user_id: uuid.UUID, message_id: uuid.UUID) -> None:
    exists = await db.execute(
        select(MessageReceipt.id).where(
            MessageReceipt.message_id == message_id, MessageReceipt.user_id == user_id
        )
    )
    if exists.first():
        return
    msg = await db.get(Message, message_id)
    if msg is None:
        return
    db.add(MessageReceipt(message_id=message_id, user_id=user_id, state=ReceiptState.delivered))
    await db.flush()
    # notifie l'expediteur : double coche grise (message.new -> "remis").
    # On relaie AUSSI `client_id` : cote client la ligne locale peut encore
    # etre indexee par client_id si la confirmation du POST n'est pas passee.
    await manager.send_to_user(
        str(msg.sender_id),
        {
            "type": "receipt.delivered",
            "conversation_id": str(msg.conversation_id),
            "message_id": str(message_id),
            "client_id": msg.client_id,
        },
    )


async def edit(db: AsyncSession, me: User, message_id: uuid.UUID, body: str) -> MessageOut:
    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")
    if msg.sender_id != me.id:
        raise ForbiddenError("message.not_owner", code="not_owner")
    age = (datetime.now(UTC) - msg.created_at).total_seconds()
    if age > _EDIT_WINDOW_SEC:
        raise ForbiddenError("message.edit_window_closed", code="edit_window_closed")

    msg.body = body
    msg.edited_at = datetime.now(UTC)
    await db.flush()

    conv = await db.get(Conversation, msg.conversation_id)
    partner_id = await _partner_id(conv, me.id)  # type: ignore[arg-type]
    await manager.send_to_user(
        str(partner_id),
        {"type": "message.edited", "message": (await _serialize(db, msg, viewer_id=partner_id)).model_dump(mode="json")},
    )
    return await _serialize(
        db, msg, viewer_id=me.id, viewer_read_receipts=me.read_receipts
    )


async def delete(db: AsyncSession, me: User, message_id: uuid.UUID) -> None:
    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")
    if msg.sender_id != me.id:
        raise ForbiddenError("message.not_owner", code="not_owner")
    msg.deleted_at = datetime.now(UTC)
    msg.body = ""
    await db.flush()

    conv = await db.get(Conversation, msg.conversation_id)
    partner_id = await _partner_id(conv, me.id)  # type: ignore[arg-type]
    await manager.send_to_user(
        str(partner_id),
        {"type": "message.deleted", "message_id": str(msg.id), "conversation_id": str(msg.conversation_id)},
    )


async def react(
    db: AsyncSession, me: User, message_id: uuid.UUID, emoji: str | None
) -> None:
    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")
    conv = await db.get(Conversation, msg.conversation_id)
    if conv is None or me.id not in (conv.user_a_id, conv.user_b_id):
        raise ForbiddenError()

    res = await db.execute(
        select(MessageReaction).where(
            MessageReaction.message_id == message_id, MessageReaction.user_id == me.id
        )
    )
    row = res.scalar_one_or_none()
    if emoji is None:
        if row:
            await db.delete(row)
    elif row:
        row.emoji = emoji
    else:
        db.add(MessageReaction(message_id=message_id, user_id=me.id, emoji=emoji))
    await db.flush()

    partner_id = await _partner_id(conv, me.id)
    await manager.send_to_user(
        str(partner_id),
        {
            "type": "message.reaction",
            "message_id": str(message_id),
            "user_id": str(me.id),
            "emoji": emoji,
        },
    )
