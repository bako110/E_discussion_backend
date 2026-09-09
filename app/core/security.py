"""Primitives d'authentification — hachage de mot de passe + JWT.

Aucune logique metier ici : juste hash/verify et encode/decode de tokens.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGO = settings.JWT_ALGORITHM


# ── Mots de passe ────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT ─────────────────────────────────────────────────────────────────────
def _encode(payload: dict[str, Any], expires: timedelta, token_type: str) -> str:
    now = datetime.now(UTC)
    to_encode = {
        **payload,
        "iat": now,
        "exp": now + expires,
        "jti": str(uuid.uuid4()),
        "type": token_type,
    }
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGO)


def create_access_token(subject: str, **extra: Any) -> str:
    return _encode(
        {"sub": subject, **extra},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(subject: str) -> str:
    return _encode({"sub": subject}, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Decode + valide la signature/expiration. Leve jwt.PyJWTError sinon."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGO])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected token type {expected_type!r}")
    return payload
