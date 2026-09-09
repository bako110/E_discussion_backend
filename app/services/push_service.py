"""Push FCM — best-effort, jamais bloquant. Degrade en log si non configure."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.push import DeviceToken

log = get_logger(__name__)

_fcm_ready = False


def _init_fcm() -> bool:
    global _fcm_ready
    if _fcm_ready:
        return True
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FCM_CREDENTIALS_FILE)
            firebase_admin.initialize_app(cred)
        _fcm_ready = True
    except Exception as e:  # pragma: no cover
        log.warning("fcm.init_failed", error=str(e))
        _fcm_ready = False
    return _fcm_ready


async def push_to_user(
    db: AsyncSession, user_id: uuid.UUID, *, title: str, body: str, data: dict[str, str] | None = None
) -> None:
    rows = await db.execute(select(DeviceToken.token).where(DeviceToken.user_id == user_id))
    tokens = [t for (t,) in rows.all()]
    if not tokens:
        return
    if not _init_fcm():
        log.info("push.console", user_id=str(user_id), title=title, body=body, data=data)
        return
    from firebase_admin import messaging  # type: ignore

    msg = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
    )
    try:
        messaging.send_each_for_multicast(msg)
    except Exception as e:  # pragma: no cover
        log.warning("push.send_failed", error=str(e))
