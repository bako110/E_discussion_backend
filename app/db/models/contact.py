"""Repertoire telephonique synchronise (comme WhatsApp) — matching par phone.

Le client envoie les numeros normalises E.164 de son carnet d'adresses ;
le backend renvoie ceux qui correspondent a un `User` existant.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class UserContact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_contacts"
    __table_args__ = (
        UniqueConstraint("owner_id", "phone", name="uq_contact_owner_phone"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)  # E.164
    display_name: Mapped[str | None] = mapped_column(String(120))  # nom tel qu'enregistre par owner

    # rempli si le numero correspond a un compte
    matched_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
