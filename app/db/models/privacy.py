"""Listes de confidentialite par champ (facon WhatsApp actuel).

Un `PrivacyAudienceEntry` = un contact liste pour UN champ de profil d'un
utilisateur. Le sens depend du mode du champ sur `users` :
  - `<field>_privacy == 'everyone_except'` -> `target` est EXCLU du champ,
  - `<field>_privacy == 'only'`            -> `target` est un des SEULS
     autorises a voir le champ,
  - autres modes                            -> les entrees sont ignorees.

Evalue a la lecture (liste courante). Chaque champ a sa propre liste.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class PrivacyField(str, enum.Enum):
    online = "online"
    last_seen = "last_seen"
    profile_photo = "profile_photo"
    about = "about"


class PrivacyAudienceEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "privacy_audience"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "field", "target_id", name="uq_privacy_audience"
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    field: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
