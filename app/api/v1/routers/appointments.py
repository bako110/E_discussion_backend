"""Router rendez-vous — /api/v1/appointments

Planification de rendez-vous multi-participants : un organisateur invite un
ou plusieurs utilisateurs, chacun accepte/decline individuellement. Des
rappels push automatiques sont envoyes a 24h, 1h et a l'heure exacte (voir
app/tasks/appointment_reminders.py).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.appointment import AppointmentCreateIn, AppointmentOut
from app.schemas.common import Message
from app.services import appointment_service

router = APIRouter()


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment(body: AppointmentCreateIn, current_user: CurrentUser, db: DbSession):
    out = await appointment_service.create(db, current_user, body)
    await db.commit()
    return out


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: str | None = Query(
        None, alias="status", pattern="^(upcoming|past|ongoing|cancelled)$"
    ),
):
    return await appointment_service.list_for_user(db, current_user, status_filter=status_filter)


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(appointment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await appointment_service.get_one(db, current_user, appointment_id)


@router.post("/{appointment_id}/accept", response_model=AppointmentOut)
async def accept_appointment(appointment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await appointment_service.accept(db, current_user, appointment_id)
    await db.commit()
    return out


@router.post("/{appointment_id}/decline", response_model=AppointmentOut)
async def decline_appointment(appointment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await appointment_service.decline(db, current_user, appointment_id)
    await db.commit()
    return out


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(appointment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await appointment_service.cancel(db, current_user, appointment_id)
    await db.commit()
    return out


@router.delete("/{appointment_id}", response_model=Message)
async def delete_appointment(appointment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await appointment_service.delete_one(db, current_user, appointment_id)
    await db.commit()
    return Message(message="deleted")
