"""Schemas groupes & chaines."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.group import GroupKind, GroupRole
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


class GroupCreate(BaseModel):
    kind: GroupKind = GroupKind.group
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=1024)
    is_public: bool = True
    # membres a ajouter d'emblee (ids utilisateurs)
    member_ids: list[uuid.UUID] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=1024)
    is_public: bool | None = None


class AddMembersIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(..., min_length=1)


class SetRoleIn(BaseModel):
    role: GroupRole


class GroupMemberOut(ORMModel):
    user: UserPublic
    role: GroupRole
    joined_at: datetime
    muted: bool = False


class GroupOut(ORMModel):
    id: uuid.UUID
    kind: GroupKind
    name: str
    description: str | None = None
    avatar_url: str | None = None
    owner_id: uuid.UUID
    invite_code: str
    is_public: bool = True
    created_at: datetime
    last_message_at: datetime | None = None

    # agregats calcules cote service
    member_count: int = 0
    unread_count: int = 0
    my_role: GroupRole | None = None
    last_message_preview: str | None = None
    # true si l'utilisateur courant peut ecrire (groupe: membre+ ; chaine: admin+)
    can_post: bool = False


class GroupPreview(ORMModel):
    """Vue publique avant de rejoindre (retour du scan QR / lien)."""

    id: uuid.UUID
    kind: GroupKind
    name: str
    description: str | None = None
    avatar_url: str | None = None
    member_count: int = 0
    is_member: bool = False


class GroupMessageCreate(BaseModel):
    type: str = Field("text", pattern="^(text|image|video)$")
    body: str = Field("", max_length=20000)
    attachment_url: str | None = Field(None, max_length=1024)
    attachment_meta: dict | None = None
    client_id: str | None = Field(None, max_length=64)


class GroupMessageOut(ORMModel):
    id: uuid.UUID
    group_id: uuid.UUID
    sender_id: uuid.UUID
    sender: UserPublic | None = None
    client_id: str | None = None
    type: str
    body: str
    attachment_url: str | None = None
    attachment_meta: dict | None = None
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class JoinIn(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=16)
