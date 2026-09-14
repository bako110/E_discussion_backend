"""Signalement d'un profil utilisateur (façon WhatsApp « Signaler »).

Contrairement au blocage (UserBlock, une seule ligne par paire), un même
utilisateur peut être signalé plusieurs fois — par la même personne (motifs
différents) ou par des personnes différentes — donc pas de contrainte
d'unicité ici. Consultable côté modération (admin) uniquement ; l'auteur du
signalement n'a aucun moyen de le voir/modifier après envoi.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ReportReason(str, enum.Enum):
    spam = "spam"
    harassment = "harassment"
    fake_profile = "fake_profile"
    inappropriate_content = "inappropriate_content"
    scam = "scam"
    other = "other"


class UserReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_reports"

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reported_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reason: Mapped[ReportReason] = mapped_column(
        Enum(ReportReason), default=ReportReason.other, nullable=False
    )
    details: Mapped[str | None] = mapped_column(Text)
