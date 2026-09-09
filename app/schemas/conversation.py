"""Schemas conversations & messages."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.message import MessageType
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


# ── Messages ───────────────────────────────────────────────────────────────
class ReplyPreview(ORMModel):
    id: uuid.UUID
    type: MessageType
    body: str
    sender_id: uuid.UUID


class MessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    # renvoye tel quel : permet au client de recoller un message qu'il a
    # envoye offline (correlation locale, evite les doublons apres sync).
    client_id: str | None = None
    type: MessageType
    body: str
    encrypted: bool
    attachment_url: str | None
    attachment_meta: dict | None
    reply_to: ReplyPreview | None = None
    forwarded_from_id: uuid.UUID | None
    # renseigne si le message est une reponse a une story
    story_id: uuid.UUID | None = None
    reaction: str | None = None            # reaction de l'utilisateur courant
    delivered: bool = False
    read: bool = False
    edited_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime


class MessageCreate(BaseModel):
    type: MessageType = MessageType.text
    body: str = Field("", max_length=20000)
    encrypted: bool = False
    attachment_url: str | None = None
    attachment_meta: dict | None = None
    reply_to_id: uuid.UUID | None = None
    forwarded_from_id: uuid.UUID | None = None
    # Idempotence offline : si un message avec ce client_id existe deja dans
    # la conversation, le backend le renvoie tel quel au lieu d'en creer un
    # doublon (rejeu de l'outbox apres reconnexion).
    client_id: str | None = Field(None, max_length=64)


class MessageEdit(BaseModel):
    body: str = Field(..., max_length=20000)


class ReactionIn(BaseModel):
    emoji: str | None = Field(None, max_length=16, description="null = retirer la reaction")


# ── Conversations ──────────────────────────────────────────────────────────
class ConversationSummary(BaseModel):
    id: uuid.UUID
    partner: UserPublic
    last_message: str | None
    last_message_type: MessageType | None
    last_message_at: datetime | None
    last_message_encrypted: bool = False
    unread_count: int = 0
    muted: bool = False
    request_status: str = "accepted"  # accepted | pending_incoming | pending_outgoing | declined


class StartConversationIn(BaseModel):
    partner_id: uuid.UUID


class ConversationDetail(BaseModel):
    id: uuid.UUID
    partner: UserPublic
    muted: bool
    request_status: str
