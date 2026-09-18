"""Schemas rendez-vous (appointments)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.db.models.appointment import AppointmentParticipantStatus, AppointmentStatus
from app.db.models.appointment_note import AppointmentNoteVisibility
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


class AppointmentCreateIn(BaseModel):
    title: str = Field(..., max_length=200, min_length=1)
    description: str | None = Field(None, max_length=4000)
    scheduled_at: datetime
    ends_at: datetime | None = None
    location: str | None = Field(None, max_length=255)
    location_map_url: str | None = Field(None, max_length=500)
    participant_user_ids: list[uuid.UUID] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_ends_after_start(self) -> "AppointmentCreateIn":
        if self.ends_at is not None and self.ends_at <= self.scheduled_at:
            raise ValueError("ends_at doit etre posterieur a scheduled_at")
        return self


class AppointmentParticipantOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    # profil public du participant — evite un aller-retour supplementaire
    # cote client pour afficher nom/avatar par ligne de participant.
    user: UserPublic
    status: AppointmentParticipantStatus
    responded_at: datetime | None = None


class AppointmentOut(ORMModel):
    id: uuid.UUID
    organizer_id: uuid.UUID
    # profil public de l'organisateur — meme raison que `user` ci-dessus.
    organizer: UserPublic
    title: str
    description: str | None = None
    scheduled_at: datetime
    ends_at: datetime | None = None
    location: str | None = None
    location_map_url: str | None = None
    status: AppointmentStatus
    created_at: datetime
    updated_at: datetime
    participants: list[AppointmentParticipantOut] = []
    # statut de L'UTILISATEUR COURANT vis-a-vis de ce rendez-vous :
    # "organizer" s'il l'a cree, sinon son AppointmentParticipantStatus.
    my_status: str = "organizer"


# valeurs acceptees par le filtre `status` de GET /appointments
AppointmentListFilter = str  # "upcoming" | "past" | "ongoing" | "cancelled"


class AppointmentNoteCreateIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    visibility: AppointmentNoteVisibility = AppointmentNoteVisibility.public


class AppointmentNoteOut(ORMModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    author: UserPublic
    visibility: AppointmentNoteVisibility
    body: str
    created_at: datetime
    updated_at: datetime
