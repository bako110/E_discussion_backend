"""Rendez-vous (appointments) — planification entre un organisateur et un ou
plusieurs participants invites, chacun acceptant/refusant individuellement.

Regles produit :
  - Un rendez-vous peut avoir PLUSIEURS participants (pas seulement 1-1).
  - Un refus individuel n'annule PAS le rendez-vous pour les autres — il
    reste 'scheduled' tant qu'au moins un participant a accepte ou n'a pas
    encore repondu. Seule une annulation explicite de l'organisateur bascule
    le statut a 'cancelled'.
  - `AppointmentReminder` trace les rappels deja envoyes (24h avant / 1h avant
    / a l'heure) pour rendre le scheduler idempotent (voir
    app/tasks/appointment_reminders.py) : la contrainte unique
    (appointment_id, kind) sert de garde-fou anti-doublon meme si deux
    executions du job se chevauchent.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    cancelled = "cancelled"


class AppointmentParticipantStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class AppointmentReminderKind(str, enum.Enum):
    h24 = "h24"
    h1 = "h1"
    at_time = "at_time"


class Appointment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "appointments"

    organizer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # heure de fin optionnelle (pas tous les rendez-vous n'en ont une definie)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # lieu en texte libre (ex: "Cafe Central, Ouaga") — saisi tel quel, pas de
    # geocodage cote serveur.
    location: Mapped[str | None] = mapped_column(String(255))
    # lien Google/Apple Maps colle par l'utilisateur, stocke tel quel (pas
    # d'integration API de cartographie).
    location_map_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus), default=AppointmentStatus.scheduled, nullable=False
    )

    participants: Mapped[list["AppointmentParticipant"]] = relationship(
        "AppointmentParticipant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AppointmentParticipant(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "appointment_participants"
    __table_args__ = (
        UniqueConstraint("appointment_id", "user_id", name="uq_appointment_participant"),
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
    status: Mapped[AppointmentParticipantStatus] = mapped_column(
        Enum(AppointmentParticipantStatus),
        default=AppointmentParticipantStatus.pending,
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppointmentReminder(Base, UUIDPrimaryKeyMixin):
    """Marque un rappel (24h/1h/heure-pile) comme deja envoye pour un
    rendez-vous — dedup exploitee par le scheduler via la contrainte unique."""

    __tablename__ = "appointment_reminders"
    __table_args__ = (
        UniqueConstraint("appointment_id", "kind", name="uq_appointment_reminder_kind"),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[AppointmentReminderKind] = mapped_column(
        Enum(AppointmentReminderKind), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
