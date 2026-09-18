"""Rendez-vous (appointments) — planification multi-participants.

Regles produit (voir aussi app/db/models/appointment.py) :
  - Plusieurs participants possibles par rendez-vous (comme un groupe).
  - Un refus individuel N'ANNULE PAS le rendez-vous pour les autres — il
    reste 'scheduled' tant qu'au moins un participant a accepte ou n'a pas
    encore repondu. Seule une annulation explicite de l'organisateur bascule
    le statut a 'cancelled'.
  - N'importe quel contact/conversation existant peut etre invite — on
    reutilise `user_service.are_contacts` (meme verification que pour
    demarrer une conversation) sans restriction supplementaire.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.models.appointment import (
    Appointment,
    AppointmentParticipant,
    AppointmentParticipantStatus,
    AppointmentStatus,
)
from app.db.models.appointment_note import (
    AppointmentHiddenByUser,
    AppointmentNote,
    AppointmentNoteVisibility,
)
from app.db.models.user import User
from app.schemas.appointment import (
    AppointmentCreateIn,
    AppointmentNoteCreateIn,
    AppointmentNoteOut,
    AppointmentOut,
    AppointmentParticipantOut,
)
from app.services import push_service, user_service
from app.services.ws_manager import manager

log = get_logger(__name__)

# fenetre "en cours" apres l'heure du rendez-vous — un rendez-vous est
# considere "ongoing" si `now` est dans [scheduled_at, scheduled_at+ONGOING[.
# 30 min est une valeur de confort arbitraire (pas de notion de duree de
# rendez-vous dans le modele) : assez court pour rester pertinent, assez
# long pour couvrir un demarrage en retard.
_ONGOING_WINDOW = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _to_out(
    db: AsyncSession,
    me: User,
    appt: Appointment,
    *,
    participants: list[AppointmentParticipant] | None = None,
) -> AppointmentOut:
    """Construit la reponse, EN Y INCLUANT le profil public (nom/avatar) de
    l'organisateur et de chaque participant — le front les affiche sans
    aller-retour supplementaire (meme raison que `GroupMemberOut.user`, voir
    app/services/group_service.py:members).

    Pas de relation ORM User <-> Appointment/AppointmentParticipant dans ce
    projet (aucun modele n'en declare vers `User`, meme `CallLog`) : on
    charge les `User` requis en un seul aller-retour puis on serialise via
    `user_service.serialize_public`, comme partout ailleurs.

    `participants` : liste explicite a utiliser si fournie (cas `create()`,
    ou l'attribut relationship `appt.participants` ne doit pas etre touche —
    voir commentaire dans `create()`). Sinon, on lit `appt.participants`
    (deja charge via `selectinload` par l'appelant).
    """
    participants = participants if participants is not None else appt.participants
    user_ids = {appt.organizer_id, *(p.user_id for p in participants)}
    users_rows = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()
    users_by_id = {u.id: u for u in users_rows}

    async def _public(user_id: uuid.UUID):
        # `users.id` est ON DELETE CASCADE sur organizer_id/user_id : une
        # ligne appointment/participant ne peut pas survivre a la suppression
        # de son utilisateur -> `user` est toujours resolvable ici.
        user = users_by_id[user_id]
        return await user_service.serialize_public(user, viewer_id=me.id)

    organizer_public = await _public(appt.organizer_id)

    out = AppointmentOut(
        id=appt.id,
        organizer_id=appt.organizer_id,
        organizer=organizer_public,
        title=appt.title,
        description=appt.description,
        scheduled_at=appt.scheduled_at,
        ends_at=appt.ends_at,
        location=appt.location,
        location_map_url=appt.location_map_url,
        status=appt.status,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
        participants=[
            AppointmentParticipantOut(
                id=p.id,
                user_id=p.user_id,
                user=await _public(p.user_id),
                status=p.status,
                responded_at=p.responded_at,
            )
            for p in participants
        ],
    )
    if appt.organizer_id == me.id:
        out.my_status = "organizer"
    else:
        mine = next((p for p in participants if p.user_id == me.id), None)
        out.my_status = mine.status.value if mine else "unknown"
    return out


async def _load_with_participants(db: AsyncSession, appointment_id: uuid.UUID) -> Appointment | None:
    return await db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(selectinload(Appointment.participants))
    )


# ── creation ────────────────────────────────────────────────────────────
async def create(db: AsyncSession, me: User, body: AppointmentCreateIn) -> AppointmentOut:
    participant_ids = {uid for uid in body.participant_user_ids if uid != me.id}
    if not participant_ids:
        raise AppError(
            "appointments.no_valid_participants", status_code=400, code="no_valid_participants"
        )

    appt = Appointment(
        organizer_id=me.id,
        title=body.title,
        description=body.description,
        scheduled_at=body.scheduled_at,
        ends_at=body.ends_at,
        location=body.location,
        location_map_url=body.location_map_url,
        status=AppointmentStatus.scheduled,
    )
    db.add(appt)
    await db.flush()

    participants: list[AppointmentParticipant] = []
    for uid in participant_ids:
        p = AppointmentParticipant(
            appointment_id=appt.id, user_id=uid, status=AppointmentParticipantStatus.pending
        )
        db.add(p)
        participants.append(p)
    await db.flush()
    # NB : on ne fait PAS `appt.participants = participants` — assigner la
    # collection relationship declenche un lazy-load de son etat courant
    # (vide, puisque `appt` vient d'etre cree) AVANT remplacement, ce qui
    # echoue en async (MissingGreenlet, SQLAlchemy ne peut pas faire d'IO
    # implicite hors greenlet). `_to_out` ci-dessous accepte directement la
    # liste locale `participants` sans passer par l'attribut ORM.

    out = await _to_out(db, me, appt, participants=participants)
    ws_payload = {"type": "appointment.new", "appointment": out.model_dump(mode="json")}

    organizer_name = me.display_name or me.username or "Quelqu'un"
    for uid in participant_ids:
        await push_service.push_to_user(
            db,
            uid,
            title="Invitation a un rendez-vous",
            body=f"{organizer_name} vous invite : {body.title}",
            data={
                "type": "appointment.invite",
                "appointment_id": str(appt.id),
                "title": body.title,
                "organizer_id": str(me.id),
                "organizer_name": organizer_name,
                "scheduled_at": body.scheduled_at.isoformat(),
            },
        )
        # WS EN PLUS du push : mise a jour immediate si l'app est ouverte
        # (le push couvre le cas app fermee/arriere-plan, avec latence FCM).
        await manager.send_to_user(str(uid), ws_payload)

    return out


# ── lecture ─────────────────────────────────────────────────────────────
def _matches_status_filter(appt: Appointment, status_filter: str | None, now: datetime) -> bool:
    if status_filter is None:
        return True
    scheduled_at = _aware(appt.scheduled_at)
    if status_filter == "cancelled":
        return appt.status == AppointmentStatus.cancelled
    if appt.status == AppointmentStatus.cancelled:
        return False
    if status_filter == "upcoming":
        return scheduled_at > now
    if status_filter == "past":
        return scheduled_at < now
    if status_filter == "ongoing":
        return scheduled_at <= now < scheduled_at + _ONGOING_WINDOW
    return True


async def list_for_user(
    db: AsyncSession, me: User, *, status_filter: str | None = None
) -> list[AppointmentOut]:
    # « masques pour moi » (voir hide()) : exclus via anti-join contre
    # `appointment_hidden_by_user`, uniquement pour MOI — l'organisateur et
    # les autres participants ne sont jamais affectes par mon masquage.
    hidden_ids_subq = (
        select(AppointmentHiddenByUser.appointment_id)
        .where(AppointmentHiddenByUser.user_id == me.id)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Appointment)
            .outerjoin(
                AppointmentParticipant, AppointmentParticipant.appointment_id == Appointment.id
            )
            .where(
                or_(
                    Appointment.organizer_id == me.id,
                    AppointmentParticipant.user_id == me.id,
                ),
                Appointment.id.not_in(hidden_ids_subq),
            )
            .options(selectinload(Appointment.participants))
            .order_by(Appointment.scheduled_at.asc())
            .distinct()
        )
    ).scalars().all()

    now = _now()
    filtered = [a for a in rows if _matches_status_filter(a, status_filter, now)]
    return [await _to_out(db, me, a) for a in filtered]


async def _load_authorized(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> Appointment:
    appt = await _load_with_participants(db, appointment_id)
    if appt is None:
        raise NotFoundError("appointments.not_found", code="appointment_not_found")
    is_organizer = appt.organizer_id == me.id
    is_participant = any(p.user_id == me.id for p in appt.participants)
    if not is_organizer and not is_participant:
        raise NotFoundError("appointments.not_found", code="appointment_not_found")
    return appt


async def get_one(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> AppointmentOut:
    appt = await _load_authorized(db, me, appointment_id)
    return await _to_out(db, me, appt)


# ── reponses participant ───────────────────────────────────────────────
async def _respond(
    db: AsyncSession,
    me: User,
    appointment_id: uuid.UUID,
    *,
    new_status: AppointmentParticipantStatus,
    notify_body: str,
) -> AppointmentOut:
    appt = await _load_with_participants(db, appointment_id)
    if appt is None:
        raise NotFoundError("appointments.not_found", code="appointment_not_found")

    participant = next((p for p in appt.participants if p.user_id == me.id), None)
    if participant is None:
        raise ForbiddenError("appointments.not_a_participant", code="not_a_participant")

    participant.status = new_status
    participant.responded_at = _now()
    await db.flush()
    # `flush()` expire les attributs scalaires de `appt` (TimestampMixin a un
    # `onupdate=func.now()` server-side sur `updated_at`) -> un simple acces
    # a `appt.updated_at` plus bas declencherait un reload synchrone
    # impossible hors greenlet (MissingGreenlet). On recharge explicitement
    # CETTE seule colonne (`attribute_names`) pour ne pas re-expirer/relancer
    # un lazy-load sur `participants`, deja charge par `selectinload`.
    await db.refresh(appt, attribute_names=["updated_at"])

    out = await _to_out(db, me, appt)
    ws_payload = {"type": "appointment.updated", "appointment": out.model_dump(mode="json")}

    responder_name = me.display_name or me.username or "Un participant"
    await push_service.push_to_user(
        db,
        appt.organizer_id,
        title="Rendez-vous",
        body=f"{responder_name} {notify_body} : {appt.title}",
        data={
            "type": "appointment.response",
            "appointment_id": str(appt.id),
            "title": appt.title,
            "responder_id": str(me.id),
            "responder_name": responder_name,
            "status": new_status.value,
        },
    )
    # WS EN PLUS du push : l'organisateur, TOUS les autres participants (leur
    # vue liste doit refleter le nouveau statut en direct) et le repondant
    # lui-meme (ses autres appareils, s'il en a plusieurs) — diffusion large
    # deliberee, cf. demande produit "tout le monde doit voir ca en live".
    recipients = {appt.organizer_id, me.id, *(p.user_id for p in appt.participants)}
    for uid in recipients:
        await manager.send_to_user(str(uid), ws_payload)

    return out


async def accept(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> AppointmentOut:
    return await _respond(
        db,
        me,
        appointment_id,
        new_status=AppointmentParticipantStatus.accepted,
        notify_body="a accepte votre rendez-vous",
    )


async def decline(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> AppointmentOut:
    return await _respond(
        db,
        me,
        appointment_id,
        new_status=AppointmentParticipantStatus.declined,
        notify_body="a decline votre rendez-vous",
    )


# ── annulation / suppression (organisateur) ──────────────────────────────
async def cancel(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> AppointmentOut:
    appt = await _load_with_participants(db, appointment_id)
    if appt is None:
        raise NotFoundError("appointments.not_found", code="appointment_not_found")
    if appt.organizer_id != me.id:
        raise ForbiddenError()
    if appt.status == AppointmentStatus.cancelled:
        return await _to_out(db, me, appt)

    appt.status = AppointmentStatus.cancelled
    await db.flush()
    # voir commentaire equivalent dans `_respond` — evite le MissingGreenlet
    # sur `appt.updated_at` lu plus bas par `_to_out`.
    await db.refresh(appt, attribute_names=["updated_at"])

    out = await _to_out(db, me, appt)
    ws_payload = {"type": "appointment.updated", "appointment": out.model_dump(mode="json")}

    for p in appt.participants:
        if p.status == AppointmentParticipantStatus.declined:
            continue
        await push_service.push_to_user(
            db,
            p.user_id,
            title="Rendez-vous annule",
            body=f"Le rendez-vous « {appt.title} » a ete annule",
            data={
                "type": "appointment.cancelled",
                "appointment_id": str(appt.id),
                "title": appt.title,
            },
        )
        # WS EN PLUS du push — mise a jour live de la vue liste/detail.
        await manager.send_to_user(str(p.user_id), ws_payload)

    return out


async def delete_one(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> None:
    appt = await db.get(Appointment, appointment_id)
    if appt is None:
        raise NotFoundError("appointments.not_found", code="appointment_not_found")
    if appt.organizer_id != me.id:
        raise ForbiddenError()
    await db.delete(appt)


# ── masquage personnel ("hide for me") ───────────────────────────────────
# Retire un rendez-vous de MA liste uniquement — l'organisateur et les
# autres participants ne voient jamais ce masquage (pas de push/WS, pas de
# changement de Appointment.status/AppointmentParticipant.status). Mirroir
# exact de conversation_service.hide/unhide (voir ConversationHide).
async def hide(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> None:
    # meme verification d'acces que get_one/_load_authorized : 404 si ni
    # organisateur ni participant (pas de fuite d'existence).
    await _load_authorized(db, me, appointment_id)
    res = await db.execute(
        select(AppointmentHiddenByUser).where(
            AppointmentHiddenByUser.user_id == me.id,
            AppointmentHiddenByUser.appointment_id == appointment_id,
        )
    )
    row = res.scalar_one_or_none()
    now = _now()
    if row is None:
        db.add(
            AppointmentHiddenByUser(user_id=me.id, appointment_id=appointment_id, hidden_at=now)
        )
    else:
        row.hidden_at = now
    await db.flush()


async def unhide(db: AsyncSession, me: User, appointment_id: uuid.UUID) -> None:
    res = await db.execute(
        select(AppointmentHiddenByUser).where(
            AppointmentHiddenByUser.user_id == me.id,
            AppointmentHiddenByUser.appointment_id == appointment_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()


# ── notes ──────────────────────────────────────────────────────────────
async def _to_note_out(db: AsyncSession, me: User, note: AppointmentNote) -> AppointmentNoteOut:
    author = await db.get(User, note.author_id)
    return AppointmentNoteOut(
        id=note.id,
        appointment_id=note.appointment_id,
        author=await user_service.serialize_public(author, viewer_id=me.id),
        visibility=note.visibility,
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def create_note(
    db: AsyncSession, me: User, appointment_id: uuid.UUID, body_in: AppointmentNoteCreateIn
) -> AppointmentNoteOut:
    # organisateur ou participant uniquement — meme verification que
    # get_one (404 si aucun des deux, pas de fuite d'existence).
    await _load_authorized(db, me, appointment_id)

    note = AppointmentNote(
        appointment_id=appointment_id,
        author_id=me.id,
        visibility=body_in.visibility,
        body=body_in.body,
    )
    db.add(note)
    await db.flush()
    return await _to_note_out(db, me, note)


async def list_notes(
    db: AsyncSession, me: User, appointment_id: uuid.UUID
) -> list[AppointmentNoteOut]:
    await _load_authorized(db, me, appointment_id)

    # visibles : toutes les notes publiques, + MES notes privees uniquement
    # (jamais les notes privees de quelqu'un d'autre).
    rows = (
        await db.execute(
            select(AppointmentNote)
            .where(
                AppointmentNote.appointment_id == appointment_id,
                or_(
                    AppointmentNote.visibility == AppointmentNoteVisibility.public,
                    and_(
                        AppointmentNote.visibility == AppointmentNoteVisibility.private,
                        AppointmentNote.author_id == me.id,
                    ),
                ),
            )
            .order_by(AppointmentNote.created_at.asc())
        )
    ).scalars().all()
    return [await _to_note_out(db, me, n) for n in rows]


async def delete_note(db: AsyncSession, me: User, note_id: uuid.UUID) -> None:
    note = await db.get(AppointmentNote, note_id)
    if note is None:
        raise NotFoundError("appointments.note_not_found", code="appointment_note_not_found")
    if note.author_id != me.id:
        raise ForbiddenError()
    await db.delete(note)
    await db.flush()
