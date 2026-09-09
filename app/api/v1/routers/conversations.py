"""Router conversations — liste, ouverture, demandes, sourdine + messages imbriques."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, PageParams
from app.schemas.common import Message
from app.schemas.conversation import (
    ConversationDetail,
    ConversationSummary,
    MessageCreate,
    MessageOut,
    SharedMediaOut,
    StartConversationIn,
)
from app.services import conversation_service, message_service

router = APIRouter()


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(current_user: CurrentUser, db: DbSession):
    return await conversation_service.list_summaries(db, current_user)


@router.post("", response_model=ConversationDetail, status_code=201)
async def start_conversation(body: StartConversationIn, current_user: CurrentUser, db: DbSession):
    conv = await conversation_service.get_or_create(db, current_user, body.partner_id)
    return await conversation_service.detail(db, current_user, conv.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await conversation_service.detail(db, current_user, conversation_id)


@router.post("/{conversation_id}/accept", response_model=Message)
async def accept(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    detail = await conversation_service.detail(db, current_user, conversation_id)
    await conversation_service.accept_request(db, current_user, detail.partner.id)
    return Message(message="accepted")


@router.post("/{conversation_id}/decline", response_model=Message)
async def decline(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    detail = await conversation_service.detail(db, current_user, conversation_id)
    await conversation_service.decline_request(db, current_user, detail.partner.id)
    return Message(message="declined")


@router.post("/{conversation_id}/mute", response_model=Message)
async def mute(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await conversation_service.set_mute(db, current_user, conversation_id, True)
    return Message(message="muted")


@router.delete("/{conversation_id}/mute", response_model=Message)
async def unmute(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await conversation_service.set_mute(db, current_user, conversation_id, False)
    return Message(message="unmuted")


# ── Messages d'une conversation ────────────────────────────────────────────
@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    page: PageParams,
    since: datetime | None = Query(
        None, description="Sync delta : ne renvoyer que ce qui a changé depuis cette date ISO"
    ),
):
    return await message_service.history(
        db,
        current_user,
        conversation_id,
        offset=page.offset,
        limit=page.limit,
        since=since,
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
async def post_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    return await message_service.send(db, current_user, conversation_id, body)


@router.put("/{conversation_id}/read", response_model=Message)
async def mark_read(conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    n = await message_service.mark_read(db, current_user, conversation_id)
    return Message(message=f"{n} marked read")


@router.delete("/{conversation_id}", response_model=Message)
async def clear_conversation(
    conversation_id: uuid.UUID, current_user: CurrentUser, db: DbSession
):
    """Efface tout l'historique de la conversation (définitif, 1-to-1)."""
    n = await conversation_service.clear_history(db, current_user, conversation_id)
    await db.commit()
    return Message(message=f"{n} messages cleared")


@router.get("/{conversation_id}/media", response_model=list[SharedMediaOut])
async def shared_media(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    page: PageParams,
):
    """Médias partagés dans la conversation (images / vidéos / fichiers / audio)."""
    return await conversation_service.list_media(
        db, current_user, conversation_id, offset=page.offset, limit=page.limit
    )
