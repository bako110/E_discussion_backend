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
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    high_priority: bool = True,
) -> None:
    """Envoi FCM **data-only**, priorité haute.

    On n'envoie PAS de bloc `notification` : le client (react-native-firebase
    + notifee) construit lui-même la notif dans son handler background, même
    app tuée. Ça permet la sonnerie d'appel plein écran et un rendu cohérent
    avec le cas app-ouverte. `title`/`body` sont passés DANS `data`.
    """
    rows = await db.execute(select(DeviceToken.token).where(DeviceToken.user_id == user_id))
    tokens = [t for (t,) in rows.all()]
    if not tokens:
        return

    payload: dict[str, str] = {k: str(v) for k, v in (data or {}).items()}
    payload.setdefault("title", title)
    payload.setdefault("body", body)

    if not _init_fcm():
        log.info("push.console", user_id=str(user_id), title=title, body=body, data=payload)
        return
    from firebase_admin import messaging  # type: ignore

    android = messaging.AndroidConfig(
        priority="high" if high_priority else "normal",
        ttl=45 if payload.get("type", "").startswith("call") else 3600,
    )
    apns = messaging.APNSConfig(
        headers={"apns-priority": "10", "apns-push-type": "background"},
        payload=messaging.APNSPayload(aps=messaging.Aps(content_available=True)),
    )
    msg = messaging.MulticastMessage(
        tokens=tokens,
        data=payload,
        android=android,
        apns=apns,
    )
    try:
        resp = messaging.send_each_for_multicast(msg)
        # nettoyage des jetons morts
        stale: list[str] = []
        for tok, res in zip(tokens, resp.responses):
            if res.success:
                continue
            err = getattr(res.exception, "code", "") or str(res.exception)
            if "registration-token-not-registered" in str(err) or "invalid-argument" in str(err):
                stale.append(tok)
        if stale:
            from app.db.models.push import DeviceToken as _DT

            await db.execute(_DT.__table__.delete().where(_DT.token.in_(stale)))
            log.info("push.pruned_stale_tokens", count=len(stale))
    except Exception as e:  # pragma: no cover
        log.warning("push.send_failed", error=str(e))
