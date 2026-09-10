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


_POLICY = r"^(all|admins)$"


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=1024)
    is_public: bool | None = None


class GroupSettingsIn(BaseModel):
    """Paramètres du groupe (admins uniquement)."""

    send_messages_policy: str | None = Field(None, pattern=_POLICY)
    edit_info_policy: str | None = Field(None, pattern=_POLICY)
    add_members_policy: str | None = Field(None, pattern=_POLICY)
    join_approval_required: bool | None = None
    invite_visibility: str | None = Field(None, pattern=r"^(both|link|code)$")
    disappearing_seconds: int | None = Field(None, ge=0, le=7776000)  # <= 90 j


class GroupSettingsOut(BaseModel):
    send_messages_policy: str = "all"
    edit_info_policy: str = "admins"
    add_members_policy: str = "all"
    join_approval_required: bool = False
    invite_visibility: str = "both"
    disappearing_seconds: int = 0


class GroupJoinRequestOut(ORMModel):
    user: UserPublic
    requested_at: datetime


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
    can_edit_info: bool = False
    can_add_members: bool = False
    # nb de demandes d'adhesion en attente (renseigne pour les admins)
    pending_requests: int = 0

    # parametres (miroir du modele — pratique pour l'ecran Parametres)
    send_messages_policy: str = "all"
    edit_info_policy: str = "admins"
    add_members_policy: str = "all"
    join_approval_required: bool = False
    invite_visibility: str = "both"
    disappearing_seconds: int = 0


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
