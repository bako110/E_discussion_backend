"""Generation des tokens d'acces LiveKit (SFU auto-heberge).

Le backend ne fait que signer un JWT court autorisant un participant a
rejoindre une room precise. Aucun flux media ne transite ici : le serveur
LiveKit (Docker, sur le VPS) relaie l'audio/video.

La cle E2EE des appels est generee cote client et n'apparait jamais dans ces
tokens ni dans les logs.
"""
from __future__ import annotations

from datetime import timedelta

from app.core.config import settings
from app.core.errors import AppError

try:  # le SDK n'est requis que si les appels sont actives
    from livekit import api as lk_api
except Exception:  # pragma: no cover
    lk_api = None  # type: ignore[assignment]


class CallsDisabledError(AppError):
    status_code = 503
    message_key = "calls.disabled"
    code = "calls_disabled"


def _ensure_ready() -> None:
    if lk_api is None or not settings.calls_enabled:
        raise CallsDisabledError()


def build_access_token(
    *,
    room_name: str,
    identity: str,
    display_name: str | None = None,
    ttl: int | None = None,
) -> str:
    """JWT autorisant `identity` a publier/souscrire dans `room_name`."""
    _ensure_ready()
    grants = lk_api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        # pas de droits admin : un participant ne peut pas lister/kicker
        room_create=False,
        room_admin=False,
        room_list=False,
    )
    token = (
        lk_api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_ttl(timedelta(seconds=ttl or settings.LIVEKIT_TOKEN_TTL))
        .with_grants(grants)
    )
    if display_name:
        token = token.with_name(display_name)
    return token.to_jwt()


def verify_webhook(body: str, auth_header: str):  # -> lk_api.WebhookEvent
    """Valide la signature d'un webhook LiveKit et retourne l'event parse."""
    _ensure_ready()
    receiver = lk_api.WebhookReceiver(
        lk_api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    )
    return receiver.receive(body, auth_header)
