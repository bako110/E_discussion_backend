"""Appels 1-to-1 WebRTC via LiveKit self-hosted.

Roles de ce backend :
  - creer la room + signer les tokens JWT d'acces LiveKit,
  - relayer la signalisation d'appel (sonnerie / accept / reject / hangup)
    via le WebSocket applicatif,
  - historiser l'appel (statut, duree) dans `call_logs`.

Le serveur LiveKit relaie les flux media. La cle E2EE (`e2ee_key`) est
generee par l'appelant : on la stocke et on la transmet au destinataire dans
l'event `call.incoming`, mais le serveur ne s'en sert jamais et ne la logge
pas.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.models.call import (
    CallDirection,
    CallLog,
    CallStatus,
    CallType,
)
from app.db.models.user import User
from app.db.redis import is_online
from app.schemas.call import (
    CallOut,
    CallStartIn,
    CallStartOut,
    CallTokenOut,
)
from app.services import livekit_service, push_service, user_service
from app.services.ws_manager import manager

log = get_logger(__name__)

# statuts pour lesquels l'appel est encore "en cours" (un seul par paire)
_LIVE = (CallStatus.ringing, CallStatus.active)

# timers de sonnerie en cours : call_id -> Task (annulés si accept/reject/cancel)
#
# NB : ce timer in-process est un mecanisme "best effort" — s'il echoue
# silencieusement pour une raison quelconque (exception avalee, task jamais
# vraiment executee...), l'appel resterait bloque en "ringing" indefiniment
# SANS lui. C'est pour ca que chaque point d'entree qui touche a un appel
# (`_load`) verifie ET corrige activement l'expiration en plus de ce timer —
# voir `_load`/`_maybe_expire_stale` : c'est ce filet de secours "lazy" qui
# garantit le comportement, le timer n'etant qu'une optimisation de latence
# (fermer la sonnerie tout de suite plutot qu'a la prochaine requete).
_ring_timers: dict[uuid.UUID, asyncio.Task] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Certains backends (SQLite en test) renvoient des datetimes naives."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _elapsed(start: datetime | None, end: datetime) -> int:
    start = _aware(start)
    if start is None:
        return 0
    return max(0, int((_aware(end) - start).total_seconds()))


async def _load(db: AsyncSession, call_id: uuid.UUID) -> CallLog:
    call = await db.get(CallLog, call_id)
    if call is None:
        raise NotFoundError("calls.not_found", code="call_not_found")
    await _maybe_expire_stale(db, call)
    return call


async def _maybe_expire_stale(db: AsyncSession, call: CallLog) -> None:
    """Filet de sécurité : si `call` sonne depuis plus de CALL_RING_TIMEOUT,
    l'expire immédiatement en 'missed'.

    Le timer in-process (`_arm_ring_timer`) est "best effort" — une tâche
    asyncio en mémoire n'est pas un mécanisme fiable à 100% (échec silencieux,
    process qui redémarre pendant que ça sonne...). Ce filet, lui, ne dépend
    d'AUCUN état en mémoire : il recalcule l'âge de l'appel à partir de
    `started_at` (persisté en DB) à chaque fois qu'on touche à un appel
    (accept/reject/cancel/hangup/consultation), donc il rattrape TOUJOURS un
    appel resté bloqué, au plus tard à la prochaine requête le concernant.
    """
    if call.status != CallStatus.ringing:
        return
    age = _elapsed(call.started_at, _now())
    if age < settings.CALL_RING_TIMEOUT:
        return
    log.info("call.stale_ringing_expired", call_id=str(call.id), age_sec=age)
    await expire_ringing(db, call.id)


def _cancel_ring_timer(call_id: uuid.UUID) -> None:
    task = _ring_timers.pop(call_id, None)
    if task is not None and not task.done():
        task.cancel()


def _arm_ring_timer(call_id: uuid.UUID) -> None:
    """Après CALL_RING_TIMEOUT sans réponse, bascule l'appel en 'missed'."""

    async def _run() -> None:
        try:
            await asyncio.sleep(settings.CALL_RING_TIMEOUT)
        except asyncio.CancelledError:
            return
        from app.db.session import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                await expire_ringing(db, call_id)
                await db.commit()
        except Exception as e:  # pragma: no cover — best effort
            # NE PAS avaler silencieusement : sans ce log, un échec ici est
            # invisible et l'appel reste bloqué en "ringing" jusqu'à ce que
            # le filet de secours `_maybe_expire_stale` (déclenché par la
            # prochaine requête d'appel) le rattrape.
            log.warning("call.ring_timer_failed", call_id=str(call_id), error=str(e))
        finally:
            _ring_timers.pop(call_id, None)

    _cancel_ring_timer(call_id)
    with contextlib.suppress(RuntimeError):
        _ring_timers[call_id] = asyncio.create_task(_run())


async def _peer_public(db: AsyncSession, me: User, other_id: uuid.UUID):
    other = await db.get(User, other_id)
    if other is None:
        return None
    is_contact = await user_service.are_contacts(db, me.id, other_id)
    return await user_service.serialize_public(
        other, viewer_id=me.id, viewer_is_contact=is_contact
    )


async def _to_out(db: AsyncSession, me: User, call: CallLog) -> CallOut:
    peer_id = call.callee_id if call.caller_id == me.id else call.caller_id
    out = CallOut.model_validate(call)
    out.peer = await _peer_public(db, me, peer_id)
    return out


# ── demarrage (appelant) ──────────────────────────────────────────────────
async def start(db: AsyncSession, me: User, body: CallStartIn) -> CallStartOut:
    if not settings.calls_enabled:
        raise livekit_service.CallsDisabledError()
    if body.callee_id == me.id:
        raise AppError("calls.cannot_call_self", status_code=400, code="call_self")

    callee = await db.get(User, body.callee_id)
    if callee is None or not callee.is_active:
        raise NotFoundError("calls.callee_not_found", code="callee_not_found")
    if await user_service.is_blocked_between(db, me.id, body.callee_id):
        raise ForbiddenError("calls.blocked", code="call_blocked")

    # Le destinataire refuse les appels d'inconnus et je ne suis pas un de ses
    # contacts -> on rejette AVANT de faire sonner (plus fiable que le client).
    if callee.call_block_unknown and not await user_service.are_contacts(
        db, body.callee_id, me.id
    ):
        raise ForbiddenError("calls.blocked", code="call_blocked")

    # 1) L'appelant a-t-il deja un appel en cours ? -> il ne peut pas en lancer
    #    un 2e (409). Couvre aussi le cas d'un appel zombie cote appelant.
    mine_live = (
        await db.execute(
            select(CallLog)
            .where(
                or_(CallLog.caller_id == me.id, CallLog.callee_id == me.id),
                CallLog.status.in_(_LIVE),
            )
            .order_by(CallLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if mine_live is not None:
        raise AppError("calls.already_in_call", status_code=409, code="already_in_call")

    # 2) Le destinataire est-il deja en appel (avec qqn d'autre) ? -> occupe.
    callee_live = (
        await db.execute(
            select(CallLog.id)
            .where(
                or_(CallLog.caller_id == body.callee_id, CallLog.callee_id == body.callee_id),
                CallLog.status.in_(_LIVE),
            )
            .limit(1)
        )
    ).first()
    if callee_live is not None:
        raise AppError("calls.callee_busy", status_code=409, code="callee_busy")

    room_name = f"call_{uuid.uuid4().hex}"
    call = CallLog(
        caller_id=me.id,
        callee_id=body.callee_id,
        call_type=body.call_type,
        direction=CallDirection.outgoing,
        status=CallStatus.ringing,
        room_name=room_name,
        e2ee_key=body.e2ee_key,  # stockee telle quelle, jamais utilisee ici
        started_at=_now(),
    )
    db.add(call)
    await db.flush()

    token = livekit_service.build_access_token(
        room_name=room_name,
        identity=str(me.id),
        display_name=me.display_name or me.username,
    )

    caller_public = await user_service.serialize_public(me, viewer_id=body.callee_id)
    # event sonnerie -> destinataire (tous ses appareils)
    await manager.send_to_user(
        str(body.callee_id),
        {
            "type": "call.incoming",
            "call_id": str(call.id),
            "room_name": room_name,
            "call_type": call.call_type.value,
            "e2ee_key": body.e2ee_key,
            "livekit_url": settings.LIVEKIT_URL,
            "caller": caller_public.model_dump(mode="json"),
            "ring_timeout": settings.CALL_RING_TIMEOUT,
        },
    )
    _caller_name = caller_public.display_name or caller_public.username or "Appel"
    await push_service.push_to_user(
        db,
        body.callee_id,
        title=_caller_name,
        body="Appel vidéo entrant" if call.call_type == CallType.video else "Appel entrant",
        data={
            "type": "call.incoming",
            "call_id": str(call.id),
            "call_type": call.call_type.value,
            "room_name": room_name,
            "caller_id": str(me.id),
            "caller_name": _caller_name,
            "caller_avatar": caller_public.avatar_url or "",
        },
    )

    # sonnerie limitée dans le temps -> 'missed' automatique
    _arm_ring_timer(call.id)

    callee_online = await is_online(str(body.callee_id))

    base = CallOut.model_validate(call)
    base.peer = await _peer_public(db, me, body.callee_id)
    return CallStartOut(
        **base.model_dump(),
        livekit_url=settings.LIVEKIT_URL,
        token=token,
        e2ee_key=call.e2ee_key,
        callee_online=callee_online,
    )


# ── acceptation (destinataire) ────────────────────────────────────────────
async def accept(db: AsyncSession, me: User, call_id: uuid.UUID) -> CallTokenOut:
    call = await _load(db, call_id)
    if call.callee_id != me.id:
        raise ForbiddenError()
    if call.status != CallStatus.ringing:
        raise AppError("calls.not_ringing", status_code=409, code="call_not_ringing")

    _cancel_ring_timer(call.id)
    call.status = CallStatus.active
    call.answered_at = _now()
    await db.flush()

    token = livekit_service.build_access_token(
        room_name=call.room_name,
        identity=str(me.id),
        display_name=me.display_name or me.username,
    )

    # prevenir l'appelant que ca decroche
    await manager.send_to_user(
        str(call.caller_id),
        {"type": "call.accepted", "call_id": str(call.id), "room_name": call.room_name},
    )
    # push EN PLUS du WS : si l'appelant a son process JS tue (app fermee)
    # juste apres avoir lance l'appel, il ne recevrait sinon jamais le signal
    # lui permettant de fermer son ecran de sonnerie sortante.
    await push_service.push_to_user(
        db,
        call.caller_id,
        title="Appel",
        body="Appel accepté",
        data={"type": "call.accepted", "call_id": str(call.id), "room_name": call.room_name},
    )

    out = CallTokenOut(
        livekit_url=settings.LIVEKIT_URL,
        token=token,
        room_name=call.room_name,
        call_type=call.call_type,
        e2ee_key=call.e2ee_key,
        peer=await _peer_public(db, me, call.caller_id),
    )
    return out


# ── refus / annulation / raccroché ───────────────────────────────────────
async def _finish(
    db: AsyncSession,
    me: User,
    call_id: uuid.UUID,
    *,
    status: CallStatus,
    event: str,
    reason: str | None = None,
) -> CallOut:
    call = await _load(db, call_id)
    if me.id not in (call.caller_id, call.callee_id):
        raise ForbiddenError()

    if call.status in (CallStatus.ended, CallStatus.rejected, CallStatus.cancelled,
                       CallStatus.missed, CallStatus.failed):
        # deja termine — on renvoie l'etat courant sans re-notifier
        return await _to_out(db, me, call)

    _cancel_ring_timer(call.id)
    call.status = status
    call.ended_at = _now()
    if call.answered_at is not None:
        call.direction = (
            CallDirection.outgoing if call.caller_id == me.id else CallDirection.incoming
        )
        call.duration_sec = _elapsed(call.answered_at, call.ended_at)
    elif status in (CallStatus.missed, CallStatus.rejected):
        call.direction = CallDirection.missed
    await db.flush()

    other_id = call.callee_id if call.caller_id == me.id else call.caller_id
    payload: dict = {
        "type": event,
        "call_id": str(call.id),
        "status": call.status.value,
        "duration_sec": call.duration_sec,
    }
    if reason:
        payload["reason"] = reason
    await manager.send_to_user(str(other_id), payload)
    # push EN PLUS du WS : couvre le cas ou l'autre partie a son process JS
    # tue (app fermee) entre le debut de la sonnerie et cette fin d'appel —
    # sans ca, sa notification plein ecran resterait bloquee indefiniment.
    await push_service.push_to_user(
        db,
        other_id,
        title="Appel",
        body="Appel terminé",
        data={
            "type": event,
            "call_id": str(call.id),
            "status": call.status.value,
            "duration_sec": str(call.duration_sec),
        },
    )
    return await _to_out(db, me, call)


async def reject(
    db: AsyncSession, me: User, call_id: uuid.UUID, *, reason: str | None = None
) -> CallOut:
    """Le destinataire refuse l'appel qui sonne (reason='busy' si deja en ligne)."""
    call = await _load(db, call_id)
    if call.callee_id != me.id:
        raise ForbiddenError()
    return await _finish(
        db, me, call_id, status=CallStatus.rejected, event="call.rejected", reason=reason
    )


async def cancel(db: AsyncSession, me: User, call_id: uuid.UUID) -> CallOut:
    """L'appelant annule avant que ça décroche."""
    call = await _load(db, call_id)
    if call.caller_id != me.id:
        raise ForbiddenError()
    status = CallStatus.cancelled if call.status == CallStatus.ringing else CallStatus.ended
    event = "call.cancelled" if status == CallStatus.cancelled else "call.ended"
    return await _finish(db, me, call_id, status=status, event=event)


async def hangup(db: AsyncSession, me: User, call_id: uuid.UUID) -> CallOut:
    """Un des deux participants raccroche un appel en cours."""
    call = await _load(db, call_id)
    if call.status == CallStatus.ringing:
        # raccroché avant réponse
        if call.caller_id == me.id:
            return await _finish(db, me, call_id, status=CallStatus.cancelled, event="call.cancelled")
        return await _finish(db, me, call_id, status=CallStatus.missed, event="call.ended")
    return await _finish(db, me, call_id, status=CallStatus.ended, event="call.ended")


async def clear_stuck(db: AsyncSession, me: User) -> int:
    """Clôt de force TOUS les appels encore 'live' impliquant l'utilisateur.

    Filet de secours contre les appels zombies (client tué sans hangup,
    perte réseau au raccroché). Appelé par le client au démarrage / avant de
    relancer un appel s'il a reçu un 409.
    """
    rows = (
        await db.execute(
            select(CallLog).where(
                or_(CallLog.caller_id == me.id, CallLog.callee_id == me.id),
                CallLog.status.in_(_LIVE),
            )
        )
    ).scalars().all()
    n = 0
    for call in rows:
        _cancel_ring_timer(call.id)
        call.status = CallStatus.ended if call.answered_at else CallStatus.cancelled
        call.ended_at = _now()
        if call.answered_at:
            call.duration_sec = _elapsed(call.answered_at, call.ended_at)
        else:
            call.direction = CallDirection.missed
        other_id = call.callee_id if call.caller_id == me.id else call.caller_id
        await manager.send_to_user(
            str(other_id),
            {
                "type": "call.ended",
                "call_id": str(call.id),
                "status": call.status.value,
                "duration_sec": call.duration_sec,
            },
        )
        await push_service.push_to_user(
            db,
            other_id,
            title="Appel",
            body="Appel terminé",
            data={
                "type": "call.ended",
                "call_id": str(call.id),
                "status": call.status.value,
                "duration_sec": str(call.duration_sec),
            },
        )
        n += 1
    await db.flush()
    return n


async def sweep_stale_ringing_calls(db: AsyncSession) -> int:
    """Balayage périodique (voir `app.main` lifespan) : expire TOUS les
    appels encore 'ringing' depuis plus de CALL_RING_TIMEOUT, tous
    utilisateurs confondus.

    Filet de sécurité de dernier recours, indépendant du timer in-process
    par appel (`_arm_ring_timer`) ET de toute requête cliente — couvre le
    cas où personne ne touche plus jamais à cet appel précis (l'appelant a
    laissé son app ouverte sans annuler, le destinataire ne décroche ni ne
    rejette) : sans ce balayage, rien ne rappellerait jamais `expire_ringing`
    pour lui.
    """
    now = _now()
    rows = (
        await db.execute(select(CallLog).where(CallLog.status == CallStatus.ringing))
    ).scalars().all()
    n = 0
    for call in rows:
        if _elapsed(call.started_at, now) < settings.CALL_RING_TIMEOUT:
            continue
        await expire_ringing(db, call.id)
        n += 1
    if n:
        await db.commit()
        log.info("call.sweep_expired", count=n)
    return n


# ── expiration de sonnerie (appelée par un worker/cron ou le client) ─────
async def expire_ringing(db: AsyncSession, call_id: uuid.UUID) -> None:
    _cancel_ring_timer(call_id)
    call = await db.get(CallLog, call_id)
    if call is None or call.status != CallStatus.ringing:
        return
    call.status = CallStatus.missed
    call.direction = CallDirection.missed
    call.ended_at = _now()
    await db.flush()
    for uid in (call.caller_id, call.callee_id):
        await manager.send_to_user(
            str(uid),
            {"type": "call.ended", "call_id": str(call.id), "status": "missed", "duration_sec": 0},
        )
        # push EN PLUS du WS — le timeout de sonnerie doit pouvoir fermer la
        # notification plein ecran meme sur un appareil dont l'app a ete
        # tuee entre le debut de la sonnerie et l'expiration.
        await push_service.push_to_user(
            db,
            uid,
            title="Appel",
            body="Appel manqué",
            data={
                "type": "call.ended",
                "call_id": str(call.id),
                "status": "missed",
                "duration_sec": "0",
            },
        )


# ── webhook LiveKit ──────────────────────────────────────────────────────
async def on_livekit_webhook(db: AsyncSession, body: str, auth_header: str) -> None:
    """Reçoit les events du serveur LiveKit (room_finished, participant_left…).

    Sert de filet de sécurité : si un participant se déconnecte brutalement,
    LiveKit ferme la room et on clôt le `CallLog` en conséquence.
    """
    event = livekit_service.verify_webhook(body, auth_header)
    room = getattr(event, "room", None)
    room_name = getattr(room, "name", "") if room else ""
    if not room_name or not room_name.startswith("call_"):
        return

    call = (
        await db.execute(select(CallLog).where(CallLog.room_name == room_name))
    ).scalar_one_or_none()
    if call is None or call.status not in _LIVE:
        return

    if event.event == "room_finished":
        _cancel_ring_timer(call.id)
        call.status = CallStatus.ended if call.answered_at else CallStatus.missed
        call.ended_at = _now()
        if call.answered_at:
            call.duration_sec = _elapsed(call.answered_at, call.ended_at)
        else:
            call.direction = CallDirection.missed
        await db.flush()
        for uid in (call.caller_id, call.callee_id):
            await manager.send_to_user(
                str(uid),
                {
                    "type": "call.ended",
                    "call_id": str(call.id),
                    "status": call.status.value,
                    "duration_sec": call.duration_sec,
                },
            )
            await push_service.push_to_user(
                db,
                uid,
                title="Appel",
                body="Appel terminé",
                data={
                    "type": "call.ended",
                    "call_id": str(call.id),
                    "status": call.status.value,
                    "duration_sec": str(call.duration_sec),
                },
            )


# ── historique ──────────────────────────────────────────────────────────
async def history(
    db: AsyncSession, me: User, *, offset: int, limit: int
) -> list[CallOut]:
    rows = (
        await db.execute(
            select(CallLog)
            .where(or_(CallLog.caller_id == me.id, CallLog.callee_id == me.id))
            .order_by(CallLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [await _to_out(db, me, c) for c in rows]


async def get_one(db: AsyncSession, me: User, call_id: uuid.UUID) -> CallOut:
    call = await _load(db, call_id)
    if me.id not in (call.caller_id, call.callee_id):
        raise ForbiddenError()
    return await _to_out(db, me, call)


async def delete_one(db: AsyncSession, me: User, call_id: uuid.UUID) -> None:
    call = await _load(db, call_id)
    if me.id not in (call.caller_id, call.callee_id):
        raise ForbiddenError()
    if call.status in _LIVE:
        raise AppError("calls.still_active", status_code=409, code="call_active")
    await db.delete(call)


async def clear_history(db: AsyncSession, me: User) -> int:
    rows = (
        await db.execute(
            select(CallLog).where(
                or_(CallLog.caller_id == me.id, CallLog.callee_id == me.id),
                CallLog.status.notin_(_LIVE),
            )
        )
    ).scalars().all()
    for c in rows:
        await db.delete(c)
    return len(rows)
