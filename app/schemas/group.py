"""Schemas groupes & chaines."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.db.models.group import GROUP_CATEGORIES, GroupKind, GroupRole
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic

# regex de validation d'un slug de categorie (ou null)
_CATEGORY = r"^(" + "|".join(GROUP_CATEGORIES) + r")$"


class GroupCreate(BaseModel):
    kind: GroupKind = GroupKind.group
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=1024)
    is_public: bool = True
    # categorie (chaines uniquement) — slug parmi GROUP_CATEGORIES
    category: str | None = Field(None, pattern=_CATEGORY)
    # membres a ajouter d'emblee (ids utilisateurs)
    member_ids: list[uuid.UUID] = Field(default_factory=list)


_POLICY = r"^(all|admins)$"


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=1024)
    is_public: bool | None = None
    category: str | None = Field(None, pattern=_CATEGORY)


class GroupSettingsIn(BaseModel):
    """Paramètres du groupe (admins uniquement)."""

    send_messages_policy: str | None = Field(None, pattern=_POLICY)
    edit_info_policy: str | None = Field(None, pattern=_POLICY)
    add_members_policy: str | None = Field(None, pattern=_POLICY)
    join_approval_required: bool | None = None
    invite_visibility: str | None = Field(None, pattern=r"^(both|link|code)$")
    disappearing_seconds: int | None = Field(None, ge=0, le=7776000)  # <= 90 j
    # CHAINE uniquement — voir Group.sign_messages
    sign_messages: bool | None = None
    # CHAINE uniquement — abonnement payant (structure seulement, voir
    # Group.is_paid). Si is_paid=True, prix + devise obligatoires.
    is_paid: bool | None = None
    subscription_price_cents: int | None = Field(None, ge=0)
    subscription_currency: str | None = Field(None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def _check_subscription_fields(self) -> "GroupSettingsIn":
        if self.is_paid:
            if self.subscription_price_cents is None or self.subscription_currency is None:
                raise ValueError(
                    "subscription_price_cents et subscription_currency sont "
                    "requis quand is_paid=True"
                )
        return self


class GroupSettingsOut(BaseModel):
    send_messages_policy: str = "all"
    edit_info_policy: str = "admins"
    add_members_policy: str = "all"
    join_approval_required: bool = False
    invite_visibility: str = "both"
    disappearing_seconds: int = 0
    sign_messages: bool = False
    is_paid: bool = False
    subscription_price_cents: int | None = None
    subscription_currency: str | None = None


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
    category: str | None = None
    # chaîne uniquement : canaux de discussion liés (jusqu'à MAX_DISCUSSION_CHANNELS)
    discussion_group_ids: list[uuid.UUID] = Field(default_factory=list)
    # canal de discussion uniquement : id de la chaîne parente (sens inverse
    # de discussion_group_ids) — None si ce groupe n'est pas un canal lié.
    parent_channel_id: uuid.UUID | None = None
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
    sign_messages: bool = False
    is_paid: bool = False
    subscription_price_cents: int | None = None
    subscription_currency: str | None = None


class GroupPreview(ORMModel):
    """Vue publique avant de rejoindre (retour du scan QR / lien, ou de
    l'annuaire des chaînes publiques)."""

    id: uuid.UUID
    kind: GroupKind
    name: str
    description: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    member_count: int = 0
    is_member: bool = False
    is_paid: bool = False
    subscription_price_cents: int | None = None
    subscription_currency: str | None = None
    # renseigne seulement pour l'annuaire (chaines publiques) — permet de
    # rejoindre directement sans repasser par un lien/QR separe.
    invite_code: str | None = None


class DiscussionLinkIn(BaseModel):
    """Lie un NOUVEAU canal de discussion (existant OU à créer) — un seul
    des deux champs doit etre fourni. Une chaîne peut en lier plusieurs
    (jusqu'à MAX_DISCUSSION_CHANNELS), voir ChannelDiscussion."""

    existing_group_id: uuid.UUID | None = None
    new_group_name: str | None = Field(None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _check_one_of(self) -> "DiscussionLinkIn":
        if bool(self.existing_group_id) == bool(self.new_group_name):
            raise ValueError(
                "fournir soit existing_group_id, soit new_group_name (un seul des deux)"
            )
        return self


class DiscussionChannelOut(ORMModel):
    """Un canal de discussion lié — id + nom, pour l'affichage de la liste."""

    id: uuid.UUID
    name: str
    avatar_url: str | None = None
    member_count: int = 0
    # présent dans list_my_linked_channels (chaîne + canaux frères dont je
    # suis membre) — absent dans list_discussions (toujours des canaux).
    kind: GroupKind | None = None


class GroupMessageCreate(BaseModel):
    type: str = Field("text", pattern="^(text|image|video|voice|file)$")
    body: str = Field("", max_length=20000)
    attachment_url: str | None = Field(None, max_length=1024)
    attachment_meta: dict | None = None
    client_id: str | None = Field(None, max_length=64)
    forwarded_from_id: uuid.UUID | None = None
    # nom de l'auteur ORIGINAL du message transféré (pas celui qui transfère,
    # deja visible comme sender du nouveau message) — fourni par le client
    # au moment du transfert, voir Group.forwarded_from_name.
    forwarded_from_name: str | None = Field(None, max_length=160)


class GroupMessageEditIn(BaseModel):
    body: str = Field(..., max_length=20000)


class GroupMessageReactIn(BaseModel):
    """emoji=null retire ma reaction."""

    emoji: str | None = Field(None, min_length=1, max_length=16)


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
    forwarded_from_id: uuid.UUID | None = None
    # nom de l'auteur ORIGINAL du message transféré — voir
    # Group.forwarded_from_name. None si ce n'est pas un transfert.
    forwarded_from_name: str | None = None
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    # reactions agregees — {emoji: count}, calcule cote service
    reactions: dict[str, int] = Field(default_factory=dict)
    # mon propre emoji sur ce message, ou None
    my_reaction: str | None = None
    # nombre de fois que CE message a ete transfere ailleurs
    forward_count: int = 0


class GroupMessageReactionOut(ORMModel):
    """Une reaction individuelle — pour la bottom sheet "qui a reagi"."""

    emoji: str
    user: UserPublic


class JoinIn(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=16)


class DiscoverChannelsOut(BaseModel):
    items: list[GroupPreview] = Field(default_factory=list)
    next_cursor: str | None = None
