"""Groupes & Chaines — conversations multi-membres.

Un `Group` couvre deux formes :
  - kind='group'   : discussion multi-membres, tout le monde peut ecrire ;
  - kind='channel' : diffusion, seuls owner/admin publient, les autres
                     ('subscriber') lisent.

Les messages sont stockes/relayes EN CLAIR (pas d'E2E de groupe pour l'instant,
comme les reponses de story). L'acces se fait via `invite_code` (QR / lien
`gofolyx://join/<code>`).
"""
from __future__ import annotations

import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB


def _gen_invite_code() -> str:
    # 10 caracteres URL-safe — suffisant pour un code d'invitation.
    return secrets.token_urlsafe(8)[:10]


# Categories de CHAINE (slugs). Libelles cote client (i18n). Sert au tri /
# filtre des chaines. Le client valide aussi cette liste.
GROUP_CATEGORIES: tuple[str, ...] = (
    "news",
    "entertainment",
    "sport",
    "tech",
    "education",
    "business",
    "lifestyle",
    "music",
    "gaming",
    "art",
    "science",
    "politics",
    "religion",
    "other",
)


class GroupKind(str, enum.Enum):
    group = "group"
    channel = "channel"


class GroupRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"        # groupe : peut ecrire
    subscriber = "subscriber"  # chaine : lecture seule


class Group(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "groups"

    kind: Mapped[GroupKind] = mapped_column(
        Enum(GroupKind), default=GroupKind.group, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, default=_gen_invite_code, nullable=False
    )
    # chaine publique : figure dans l'annuaire "chaines populaires"
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # categorie d'une CHAINE (slug parmi GROUP_CATEGORIES) — sert au tri /
    # filtre. Null pour un groupe (sans objet).
    category: Mapped[str | None] = mapped_column(String(24), index=True)

    # ── Parametres (facon WhatsApp — admins uniquement) ──────────────────
    # 'all' (tous les membres) | 'admins' (lecture seule pour les autres)
    send_messages_policy: Mapped[str] = mapped_column(
        String(10), default="all", nullable=False
    )
    edit_info_policy: Mapped[str] = mapped_column(
        String(10), default="admins", nullable=False
    )
    add_members_policy: Mapped[str] = mapped_column(
        String(10), default="all", nullable=False
    )
    # les demandes via lien doivent etre approuvees par un admin
    join_approval_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # ce qui est montre aux membres : 'both' | 'link' | 'code'
    invite_visibility: Mapped[str] = mapped_column(
        String(10), default="both", nullable=False
    )
    # disparition auto des messages, en SECONDES (0 = desactive)
    disappearing_seconds: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class GroupMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[GroupRole] = mapped_column(
        Enum(GroupRole), default=GroupRole.member, nullable=False
    )
    # marqueur "lu jusqu'a" pour le compteur de non-lus
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GroupJoinRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Demande d'adhesion en attente (quand `join_approval_required`)."""

    __tablename__ = "group_join_requests"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_join_req"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )


class GroupMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "group_messages"
    __table_args__ = (
        UniqueConstraint("group_id", "client_id", name="uq_group_msg_client"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 'text' | 'image' | 'video' | 'system' (arrivee/depart d'un membre…)
    type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(1024))
    attachment_meta: Mapped[dict | None] = mapped_column(JSONB)
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)

    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
