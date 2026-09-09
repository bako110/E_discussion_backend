"""Generation / verification de codes OTP.

Double stockage :
- Redis (`otp:{purpose}:{identifier}`) : chemin rapide + TTL natif + compteur
  d'essais. C'est la source de verite pour la verification.
- Postgres (`otp_challenges`) : trace d'audit, non lue au verify.

Le code n'est jamais stocke en clair : seul son hash bcrypt est conserve.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import RateLimitError
from app.core.security import hash_password, verify_password
from app.db.models.auth import OtpChallenge, OtpChannel, OtpPurpose
from app.db.redis import get_redis
from app.i18n import translate
from app.services.notifier import send_email, send_sms
from app.utils.phone import looks_like_phone

_SEND_COOLDOWN_SEC = 30


def _gen_code() -> str:
    lo = 10 ** (settings.OTP_LENGTH - 1)
    hi = 10**settings.OTP_LENGTH - 1
    return str(secrets.randbelow(hi - lo + 1) + lo)


def _channel_for(identifier: str) -> OtpChannel:
    return OtpChannel.sms if looks_like_phone(identifier) else OtpChannel.email


async def request_otp(
    db: AsyncSession,
    *,
    identifier: str,
    purpose: str,
    locale: str,
    user_id: str | None = None,
) -> str:
    """Genere un code, l'envoie par le bon canal, le stocke (Redis + audit).
    Retourne le canal utilise ('sms' | 'email')."""
    r = get_redis()
    key = f"otp:{purpose}:{identifier}"
    cooldown_key = f"{key}:cooldown"

    if await r.exists(cooldown_key):
        raise RateLimitError()

    code = _gen_code()
    code_hash = hash_password(code)
    ttl_min = settings.OTP_TTL_SECONDS // 60

    await r.hset(key, mapping={"hash": code_hash, "attempts": "0"})
    await r.expire(key, settings.OTP_TTL_SECONDS)
    await r.set(cooldown_key, "1", ex=_SEND_COOLDOWN_SEC)

    channel = _channel_for(identifier)
    if channel is OtpChannel.sms:
        await send_sms(identifier, translate("otp.sms_body", locale, code=code, ttl_min=ttl_min))
    else:
        await send_email(
            identifier,
            translate("otp.email_subject", locale),
            translate("otp.email_body", locale, code=code, ttl_min=ttl_min),
        )

    db.add(
        OtpChallenge(
            channel=channel,
            purpose=OtpPurpose(purpose),
            identifier=identifier,
            code_hash=code_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.OTP_TTL_SECONDS),
            user_id=uuid.UUID(user_id) if user_id else None,
        )
    )
    await db.flush()
    return channel.value


async def verify_otp(*, identifier: str, purpose: str, code: str, locale: str) -> None:
    """Leve AppError si invalide/expire/trop d'essais. Consomme le code si OK."""
    from app.core.errors import AppError

    r = get_redis()
    key = f"otp:{purpose}:{identifier}"
    data = await r.hgetall(key)
    if not data:
        raise AppError("otp.expired", status_code=400, code="otp_expired")

    attempts = int(data.get("attempts", "0"))
    if attempts >= settings.OTP_MAX_ATTEMPTS:
        await r.delete(key)
        raise AppError("otp.too_many_attempts", status_code=429, code="otp_locked")

    if not verify_password(code, data["hash"]):
        await r.hincrby(key, "attempts", 1)
        raise AppError("otp.invalid", status_code=400, code="otp_invalid")

    await r.delete(key)
