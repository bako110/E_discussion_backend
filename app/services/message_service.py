"""Messages — envoi, historique, edition, suppression, reactions, accuses.

Le backend ne dechiffre jamais : si `encrypted=True`, `body` est le blob
Double Ratchet serialise, stocke et relaye tel quel.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, desc, func, or_, select
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
from app.services import conversation_service, media_service, user_service
from app.services.push_service import push_to_user
from app.services.ws_manager import manager

# Types de piece jointe pouvant etre envoyes en "vue unique" (facon
# WhatsApp) — le texte et la localisation en sont exclus.
_VIEW_ONCE_TYPES = {MessageType.image, MessageType.video, MessageType.voice, MessageType.file}

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

    delivered = read = played = False
    if m.sender_id == viewer_id:
        rc = await db.execute(
            select(MessageReceipt.state, MessageReceipt.played_at).where(
                MessageReceipt.message_id == m.id
            )
        )
        states: set = set()
        for st, played_at in rc.all():
            states.add(st)
            if played_at is not None:
                played = True
        delivered = ReceiptState.delivered in states or ReceiptState.read in states
        # reciprocite WhatsApp : si J'AI desactive les accuses de lecture, je ne
        # vois pas non plus quand l'autre a lu / ecoute mes messages.
        read = viewer_read_receipts and (ReceiptState.read in states)
        played = viewer_read_receipts and played

    out = MessageOut.model_validate(m)
    out.reply_to = reply
    out.reaction = my_reaction
    out.delivered = delivered
    out.read = read
    out.played = played
    out.view_once_opened = m.view_once_opened_at is not None
    return out


async def send(
    db: AsyncSession, me: User, conversation_id: uuid.UUID, data: MessageCreate
) -> MessageOut:
    conv = await conversation_service.get_owned(db, me, conversation_id)
    partner_id = await _partner_id(conv, me.id)

    if await user_service.is_blocked_between(db, me.id, partner_id):
        raise ForbiddenError("conversation.blocked", code="blocked")

    # Idempotence : rejeu de l'outbox apres reconnexion -> renvoyer le message
    # deja cree pour ce client_id au lieu d'un doublon. AVANT les controles de
    # demande ci-dessous : un retry ne doit jamais etre compte comme un
    # nouvel essai (ni faire echouer sur la limite des 3 messages).
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

    # demande refusee -> reversible, mais pas silencieux : l'initiateur voit
    # une erreur explicite lui disant d'attendre l'acceptation, plutot que de
    # relancer une nouvelle demande a son insu a chaque tentative.
    status = await conversation_service.request_status(db, me.id, partner_id)
    if status == "declined":
        raise ForbiddenError("conversation.request_declined", code="request_declined")

    # demande en attente (je suis l'initiateur, l'autre n'a pas encore
    # repondu) -> maximum 3 messages avant reponse, pour eviter le spam d'un
    # inconnu ; au-dela, il doit attendre l'acceptation pour continuer.
    if status == "pending_outgoing":
        count_res = await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv.id,
                Message.sender_id == me.id,
                Message.deleted_at.is_(None),
            )
        )
        sent_count = count_res.scalar_one()
        if sent_count >= 3:
            raise ForbiddenError(
                "conversation.request_limit_reached", code="request_limit_reached"
            )

    if data.type == MessageType.text and not data.body.strip() and not data.attachment_url:
        raise AppError("errors.validation", status_code=422, code="empty_message")

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
        # vue unique : ignore silencieusement pour un type non pris en charge
        # (texte/localisation) plutot que de rejeter l'envoi.
        view_once=bool(data.view_once and data.type in _VIEW_ONCE_TYPES and data.attachment_url),
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
                "sender_avatar": me.avatar_url or "",
                "message_id": str(msg.id),
                # "message_type" est une clé RÉSERVÉE par FCM -> Firebase
                # rejette TOUT le payload avec "INVALID_ARGUMENT: Invalid
                # data payload key: message_type" (silencieux côté client,
                # aucune notification n'arrive jamais). Jamais lue côté app
                # (grep sans résultat dans fcm.ts) -> simplement retirée.
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
            # vue unique ouverte APRÈS `since` mais envoyée avant : sans cette
            # condition, l'expéditeur ne recevait la bulle "consulté(e)" QUE
            # via le WS temps réel — jamais rattrapée par le pull delta si
            # son chat/app était fermé au moment de l'ouverture (WS manqué).
            | (Message.view_once_opened_at > since)
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

    now = datetime.now(UTC)
    senders: set[uuid.UUID] = set()
    for msg, receipt in rows:
        if receipt is None:
            db.add(
                MessageReceipt(
                    message_id=msg.id,
                    user_id=me.id,
                    state=ReceiptState.read,
                    delivered_at=now,
                    read_at=now,
                )
            )
        else:
            receipt.state = ReceiptState.read
            if receipt.delivered_at is None:
                receipt.delivered_at = receipt.created_at or now
            if receipt.read_at is None:
                receipt.read_at = now
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
    db.add(
        MessageReceipt(
            message_id=message_id,
            user_id=user_id,
            state=ReceiptState.delivered,
            delivered_at=datetime.now(UTC),
        )
    )
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


async def mark_played(db: AsyncSession, me: User, message_id: uuid.UUID) -> None:
    """Le destinataire a ECOUTE un vocal / OUVERT une video. Horodate une seule
    fois `played_at` et previent l'expediteur (WS `receipt.played`)."""
    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")
    if msg.sender_id == me.id:
        return  # l'expediteur ne "joue" pas son propre message
    # le lecteur doit appartenir a la conversation
    await conversation_service.get_owned(db, me, msg.conversation_id)

    now = datetime.now(UTC)
    receipt = await db.scalar(
        select(MessageReceipt).where(
            MessageReceipt.message_id == message_id,
            MessageReceipt.user_id == me.id,
        )
    )
    if receipt is None:
        receipt = MessageReceipt(
            message_id=message_id,
            user_id=me.id,
            state=ReceiptState.delivered,
            delivered_at=now,
            played_at=now,
        )
        db.add(receipt)
    elif receipt.played_at is None:
        receipt.played_at = now
    else:
        return  # deja horodate
    await db.flush()

    if me.read_receipts:
        await manager.send_to_user(
            str(msg.sender_id),
            {
                "type": "receipt.played",
                "conversation_id": str(msg.conversation_id),
                "message_id": str(message_id),
            },
        )


async def consume_view_once(db: AsyncSession, me: User, message_id: uuid.UUID) -> None:
    """Le destinataire vient d'OUVRIR une piece jointe vue-unique. Efface
    definitivement le fichier (disque + `attachment_url`/`attachment_meta`)
    et previent l'expediteur (WS `message.view_once_opened`) pour qu'il
    affiche la bulle grisee "consulte(e)" chez lui aussi. Idempotent : une
    2e tentative (retry offline, double-tap) ne fait rien de plus."""
    msg = await db.get(Message, message_id)
    if msg is None or msg.deleted_at is not None:
        raise NotFoundError("message.not_found", code="message_not_found")
    if not msg.view_once:
        raise AppError("message.not_view_once", status_code=422, code="not_view_once")
    if msg.sender_id == me.id:
        return  # l'expediteur ne "consomme" pas son propre envoi
    # le lecteur doit appartenir a la conversation
    await conversation_service.get_owned(db, me, msg.conversation_id)

    if msg.view_once_opened_at is not None:
        return  # deja consomme (retry idempotent)

    media_service.delete_by_url(msg.attachment_url)
    thumb = (msg.attachment_meta or {}).get("thumbnail_url") if msg.attachment_meta else None
    media_service.delete_by_url(thumb)

    msg.view_once_opened_at = datetime.now(UTC)
    msg.attachment_url = None
    msg.attachment_meta = None
    await db.flush()

    await manager.send_to_user(
        str(msg.sender_id),
        {
            "type": "message.view_once_opened",
            "conversation_id": str(msg.conversation_id),
            "message_id": str(message_id),
        },
    )


async def message_info(db: AsyncSession, me: User, message_id: uuid.UUID) -> dict:
    """Ecran « Infos » (expediteur uniquement) : horodatages distribue / lu /
    ecoute-ouvert du destinataire."""
    msg = await db.get(Message, message_id)
    if msg is None:
        raise NotFoundError("message.not_found", code="message_not_found")
    if msg.sender_id != me.id:
        raise ForbiddenError("message.not_owner", code="not_owner")

    receipt = await db.scalar(
        select(MessageReceipt).where(MessageReceipt.message_id == message_id)
    )
    return {
        "type": msg.type.value,
        "sent_at": msg.created_at,
        "delivered_at": receipt.delivered_at if receipt else None,
        "read_at": receipt.read_at if receipt else None,
        "played_at": receipt.played_at if receipt else None,
    }


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
