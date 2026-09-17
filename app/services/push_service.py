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
        log.info("push.no_device_token", user_id=str(user_id), type=(data or {}).get("type"))
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
        # nettoyage des jetons morts + visibilité sur les échecs NON-stale
        # (silencieux jusqu'ici : un push qui échoue pour une autre raison —
        # quota, credentials, throttling OEM côté FCM — ne laissait AUCUNE
        # trace alors que l'appel `push_to_user` ne levait aucune exception).
        stale: list[str] = []
        other_failures = 0
        for tok, res in zip(tokens, resp.responses):
            if res.success:
                continue
            code = getattr(res.exception, "code", "")
            err = f"{code}: {res.exception}" if code else str(res.exception)
            err_lower = str(err).lower()
            # tokens définitivement morts -> à purger pour ne plus jamais
            # retenter (et ne pas gonfler indéfiniment la liste par device).
            #
            # ATTENTION : "INVALID_ARGUMENT" est un code GÉNÉRIQUE côté
            # Firebase — il couvre AUSSI bien un token malformé/mort qu'un
            # PAYLOAD invalide (ex: clé de `data` réservée par FCM, comme
            # "message_type" découvert en prod : "Invalid data payload key").
            # Le classer stale sur ce seul code a fait SUPPRIMER un token
            # parfaitement valide à chaque tentative alors que la vraie cause
            # était le payload -> on ne considère stale que le message le
            # plus spécifique possible ("registration token is not a valid
            # FCM registration token"), jamais le code générique seul.
            is_stale = (
                "registration-token-not-registered" in err_lower
                or "registration_token_not_registered" in err_lower
                or "unregistered" in err_lower
                or "not a valid fcm registration token" in err_lower
                # variante Admin SDK observee en prod : "NOT_FOUND: NotRegistered"
                # ("notregistered" colle, sans tiret ni underscore) — sans ce
                # pattern, ces tokens ne sont jamais classes stale ni purges,
                # et s'accumulent indefiniment (10 tokens/compte apres une
                # semaine de tests, 9 morts a chaque envoi).
                or "notregistered" in err_lower
            )
            # log SYSTÉMATIQUE de la raison exacte, même pour un token classé
            # stale -> indispensable pour diagnostiquer SI "invalid argument"
            # cache en fait une autre cause (payload malformé, mismatch de
            # certificat/SHA...) plutôt qu'un vrai token mort.
            log.warning(
                "push.token_send_failed",
                user_id=str(user_id),
                type=payload.get("type"),
                token_suffix=tok[-8:],
                error=str(err),
                classified_stale=is_stale,
            )
            if is_stale:
                stale.append(tok)
            else:
                other_failures += 1
        log.info(
            "push.sent",
            user_id=str(user_id),
            type=payload.get("type"),
            tokens=len(tokens),
            success=resp.success_count,
            failed=len(tokens) - resp.success_count,
            stale=len(stale),
            other_failures=other_failures,
        )
        if stale:
            from app.db.models.push import DeviceToken as _DT

            await db.execute(_DT.__table__.delete().where(_DT.token.in_(stale)))
            log.info("push.pruned_stale_tokens", count=len(stale))
    except Exception as e:  # pragma: no cover
        log.warning("push.send_failed", user_id=str(user_id), type=payload.get("type"), error=str(e))
