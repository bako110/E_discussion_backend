"""Notes de rendez-vous — chaque participant (ou l'organisateur) peut ajouter
une note libre sur un rendez-vous, privee (visible par son seul auteur) ou
publique (visible par tous les participants + l'organisateur).

Pas de notion d'edition dans ce module : une note se cree ou se supprime
(par son auteur uniquement), voir app/services/appointment_service.py.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AppointmentNoteVisibility(str, enum.Enum):
    private = "private"
    public = "public"


class AppointmentNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "appointment_notes"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    visibility: Mapped[AppointmentNoteVisibility] = mapped_column(
        Enum(AppointmentNoteVisibility),
        default=AppointmentNoteVisibility.public,
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class AppointmentHiddenByUser(Base, UUIDPrimaryKeyMixin):
    """« Retirer de ma liste » — masque un rendez-vous SEULEMENT pour
    l'utilisateur qui a masque, jamais pour l'organisateur ni les autres
    participants (meme principe que `ConversationHide`, voir
    app/db/models/conversation.py). Ne touche jamais a `Appointment.status`
    ni `AppointmentParticipant.status`."""

    __tablename__ = "appointment_hidden_by_user"
    __table_args__ = (
        UniqueConstraint("appointment_id", "user_id", name="uq_appointment_hidden_user"),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    hidden_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
