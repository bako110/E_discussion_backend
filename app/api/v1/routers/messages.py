"""Router messages — operations sur un message individuel (edit, delete, react)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.conversation import MessageEdit, MessageOut, ReactionIn
from app.services import message_service

router = APIRouter()


@router.patch("/{message_id}", response_model=MessageOut)
async def edit_message(
    message_id: uuid.UUID, body: MessageEdit, current_user: CurrentUser, db: DbSession
):
    return await message_service.edit(db, current_user, message_id, body.body)


@router.delete("/{message_id}", response_model=Message)
async def delete_message(message_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Suppression POUR TOUS (auteur uniquement) : pose un tombstone et pousse
    `message.deleted` au partenaire. La suppression "pour moi" est purement
    locale cote client (offline-first) et ne passe pas par le serveur."""
    await message_service.delete(db, current_user, message_id)
    return Message(message="deleted")


@router.post("/{message_id}/react", response_model=Message)
async def react_message(
    message_id: uuid.UUID, body: ReactionIn, current_user: CurrentUser, db: DbSession
):
    await message_service.react(db, current_user, message_id, body.emoji)
    return Message(message="ok")


@router.post("/{message_id}/delivered", response_model=Message)
async def ack_delivered(message_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await message_service.mark_delivered(db, current_user.id, message_id)
    return Message(message="ok")
