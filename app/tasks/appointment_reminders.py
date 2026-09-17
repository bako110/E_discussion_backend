"""Rappels automatiques de rendez-vous — 24h avant / 1h avant / a l'heure.

Execute toutes les 60s par un job APScheduler enregistre dans le lifespan de
`app.main` (une session DB fraiche est creee a chaque run, jamais la
dependance FastAPI request-scoped — voir `run_reminder_check`).

Idempotence : `AppointmentReminder` porte une contrainte unique
(appointment_id, kind). On tente d'inserer la ligne AVANT d'envoyer le push ;
si elle existe deja (IntegrityError), le rappel a deja ete envoye par une
execution precedente/concurrente -> on l'ignore silencieusement. Ca rend le
job sur sans verrou distribue, meme si deux runs se chevauchent (ex: job lent
+ tick suivant qui demarre quand meme).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models.appointment import (
    Appointment,
    AppointmentParticipantStatus,
    AppointmentReminder,
    AppointmentReminderKind,
    AppointmentStatus,
)
from app.services import push_service

log = get_logger(__name__)

# tolerance autour de chaque seuil (24h/1h/heure-pile) — le job tourne toutes
# les 60s, une fenetre de +/-1 min garantit qu'aucun tick ne rate le seuil
# meme en cas de leger jitter du scheduler.
_TOLERANCE = timedelta(minutes=1)

# fenetre de balayage : on ne scanne que les rendez-vous dont scheduled_at
# tombe entre (now - 2min) et (now + 25h) — couvre les 3 seuils (24h, 1h,
# heure-pile) sans jamais parcourir toute la table.
_SCAN_PAST = timedelta(minutes=2)
_SCAN_FUTURE = timedelta(hours=25)

_THRESHOLDS: tuple[tuple[AppointmentReminderKind, timedelta], ...] = (
    (AppointmentReminderKind.h24, timedelta(hours=24)),
    (AppointmentReminderKind.h1, timedelta(hours=1)),
    (AppointmentReminderKind.at_time, timedelta(0)),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _due_kinds(scheduled_at: datetime, now: datetime) -> list[AppointmentReminderKind]:
    """Quels seuils (24h/1h/heure-pile) sont "atteints" a `now`, a +/-1 min."""
    due = []
    for kind, delta in _THRESHOLDS:
        trigger_at = scheduled_at - delta
        if abs((now - trigger_at).total_seconds()) <= _TOLERANCE.total_seconds():
            due.append(kind)
    return due


def _reminder_text(kind: AppointmentReminderKind, title: str) -> tuple[str, str]:
    if kind == AppointmentReminderKind.h24:
        return "Rappel de rendez-vous", f"« {title} » a lieu dans 24 heures"
    if kind == AppointmentReminderKind.h1:
        return "Rappel de rendez-vous", f"« {title} » a lieu dans 1 heure"
    return "Rendez-vous", f"« {title} » commence maintenant"


async def _try_mark_sent(db: AsyncSession, appointment_id, kind: AppointmentReminderKind) -> bool:
    """Insere la ligne de dedup dans SA PROPRE transaction courte (SAVEPOINT).

    Retourne True si c'est bien CE run qui a "gagne" le droit d'envoyer le
    rappel (insertion reussie), False si un autre run l'a deja envoye
    (violation de la contrainte unique -> IntegrityError attrapee).
    """
    try:
        async with db.begin_nested():
            db.add(
                AppointmentReminder(
                    appointment_id=appointment_id,
                    kind=kind,
                    sent_at=_now(),
                )
            )
            await db.flush()
        return True
    except IntegrityError:
        log.info(
            "appointment_reminder.already_sent",
            appointment_id=str(appointment_id),
            kind=kind.value,
        )
        return False


async def check_and_send_reminders(db: AsyncSession) -> int:
    """Point d'entree appele par le job APScheduler toutes les 60s.

    Retourne le nombre de rappels effectivement envoyes (pour logging).
    """
    now = _now()
    window_start = now - _SCAN_PAST
    window_end = now + _SCAN_FUTURE

    rows = (
        await db.execute(
            select(Appointment)
            .where(
                Appointment.status == AppointmentStatus.scheduled,
                Appointment.scheduled_at >= window_start,
                Appointment.scheduled_at <= window_end,
            )
            .options(selectinload(Appointment.participants))
        )
    ).scalars().all()

    sent_count = 0
    for appt in rows:
        scheduled_at = _aware(appt.scheduled_at)
        for kind in _due_kinds(scheduled_at, now):
            won = await _try_mark_sent(db, appt.id, kind)
            if not won:
                continue

            title, body = _reminder_text(kind, appt.title)
            recipients = {appt.organizer_id}
            for p in appt.participants:
                if p.status != AppointmentParticipantStatus.declined:
                    recipients.add(p.user_id)

            for user_id in recipients:
                await push_service.push_to_user(
                    db,
                    user_id,
                    title=title,
                    body=body,
                    data={
                        "type": "appointment.reminder",
                        "appointment_id": str(appt.id),
                        "title": appt.title,
                        "kind": kind.value,
                        "scheduled_at": scheduled_at.isoformat(),
                    },
                )
            sent_count += 1
            log.info(
                "appointment_reminder.sent",
                appointment_id=str(appt.id),
                kind=kind.value,
                recipients=len(recipients),
            )

    if sent_count:
        await db.commit()
    return sent_count


async def run_reminder_check() -> None:
    """Wrapper appele directement par le job APScheduler — ouvre/ferme sa
    PROPRE session DB (jamais la dependance FastAPI request-scoped)."""
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await check_and_send_reminders(db)
    except Exception as e:  # pragma: no cover — ne doit jamais tuer le scheduler
        log.warning("appointment_reminder.check_failed", error=str(e))
