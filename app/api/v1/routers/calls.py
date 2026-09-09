"""Router appels WebRTC — /api/v1/calls

Signalisation d'appel + delivrance des tokens LiveKit (SFU auto-heberge).
Aucun flux media ne passe par ici.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, status

from app.api.deps import CurrentUser, DbSession, PageParams
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.schemas.call import CallOut, CallStartIn, CallStartOut, CallTokenOut
from app.schemas.common import Message
from app.services import call_service

router = APIRouter()
log = get_logger(__name__)


@router.get("/config")
async def calls_config(current_user: CurrentUser):
    """Indique au client si les appels sont disponibles + l'URL du SFU."""
    return {
        "enabled": settings.calls_enabled,
        "livekit_url": settings.LIVEKIT_URL if settings.calls_enabled else None,
        "ring_timeout": settings.CALL_RING_TIMEOUT,
    }


@router.get("", response_model=list[CallOut])
async def call_history(current_user: CurrentUser, db: DbSession, page: PageParams):
    return await call_service.history(
        db, current_user, offset=page.offset, limit=page.limit
    )


@router.post("", response_model=CallStartOut, status_code=status.HTTP_201_CREATED)
async def start_call(body: CallStartIn, current_user: CurrentUser, db: DbSession):
    """Demarre un appel : cree la room, sonne chez le destinataire, renvoie le
    token LiveKit de l'appelant."""
    out = await call_service.start(db, current_user, body)
    await db.commit()
    return out


@router.get("/{call_id}", response_model=CallOut)
async def get_call(call_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await call_service.get_one(db, current_user, call_id)


@router.post("/{call_id}/accept", response_model=CallTokenOut)
async def accept_call(call_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await call_service.accept(db, current_user, call_id)
    await db.commit()
    return out


@router.post("/{call_id}/reject", response_model=CallOut)
async def reject_call(
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    reason: str | None = None,
):
    out = await call_service.reject(db, current_user, call_id, reason=reason)
    await db.commit()
    return out


@router.post("/{call_id}/cancel", response_model=CallOut)
async def cancel_call(call_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await call_service.cancel(db, current_user, call_id)
    await db.commit()
    return out


@router.post("/{call_id}/hangup", response_model=CallOut)
async def hangup_call(call_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    out = await call_service.hangup(db, current_user, call_id)
    await db.commit()
    return out


@router.delete("/{call_id}", response_model=Message)
async def delete_call(call_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await call_service.delete_one(db, current_user, call_id)
    await db.commit()
    return Message(message="deleted")


@router.delete("", response_model=Message)
async def clear_calls(current_user: CurrentUser, db: DbSession):
    n = await call_service.clear_history(db, current_user)
    await db.commit()
    return Message(message=f"{n} entries cleared")


@router.post("/clear-stuck", response_model=Message)
async def clear_stuck_calls(current_user: CurrentUser, db: DbSession):
    """Clôt de force tout appel encore « en cours » impliquant l'utilisateur
    (récupération après crash / perte réseau — évite les 409 fantômes)."""
    n = await call_service.clear_stuck(db, current_user)
    await db.commit()
    return Message(message=f"{n} calls cleared")


# ── webhook LiveKit (non authentifie JWT app — signe par la cle API LiveKit) ─
@router.post("/webhooks/livekit", include_in_schema=False)
async def livekit_webhook(request: Request, authorization: str = Header("")):
    body = (await request.body()).decode("utf-8")
    try:
        async with AsyncSessionLocal() as db:
            await call_service.on_livekit_webhook(db, body, authorization)
            await db.commit()
    except Exception as e:  # pragma: no cover — ne jamais faire echouer LiveKit
        log.warning("livekit.webhook.error", error=str(e))
    return {"ok": True}
