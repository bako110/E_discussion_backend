"""Modele utilisateur — identifie par e-mail ET/OU numero de telephone.

Au moins un des deux (`email`, `phone`) est requis a la creation ; l'autre
peut etre lie plus tard (`/auth/phone/link`, `/auth/email/link`).
`password_hash` est optionnel : un compte cree par OTP telephone n'a pas
forcement de mot de passe.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    # ── Identifiants ─────────────────────────────────────────────────────
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)  # E.164
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    password_hash: Mapped[str | None] = mapped_column(String(255))

    # ── Profil ──────────────────────────────────────────────────────────
    display_name: Mapped[str | None] = mapped_column(String(80))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    about: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(8), default="fr", nullable=False)

    # ── Etat ────────────────────────────────────────────────────────────
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Confidentialite ─────────────────────────────────────────────────
    # 'everyone' | 'contacts' | 'nobody' — qui voit quoi sur le profil public
    last_seen_privacy: Mapped[str] = mapped_column(
        String(16), default="everyone", nullable=False
    )
    profile_photo_privacy: Mapped[str] = mapped_column(
        String(16), default="everyone", nullable=False
    )
    about_privacy: Mapped[str] = mapped_column(
        String(16), default="everyone", nullable=False
    )
    # accuses de lecture : si False, on n'envoie ni ne recoit les "vu"
    read_receipts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Preferences d'appel (synchronisees entre appareils) ─────────────
    # 'default' | 'classic' | 'soft'
    call_ringtone: Mapped[str] = mapped_column(String(16), default="default", nullable=False)
    call_vibrate: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # decrocher directement en haut-parleur
    call_answer_on_speaker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # mode donnees reduites : la video demarre coupee
    call_low_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # refuser cote SERVEUR les appels de personnes hors de mes contacts
    call_block_unknown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        who = self.username or self.email or self.phone
        return f"<User {who} ({self.id})>"
