"""Logique d'authentification — inscription/connexion par e-mail ET/OU telephone.

Flux :
  - register(email+password)  -> compte cree, OTP e-mail -> verify -> tokens
  - register(phone)           -> compte cree, OTP SMS     -> verify -> tokens
  - login(identifier+password)-> tokens (si e-mail/username verifie)
  - login par OTP SMS         -> send_otp(login) -> verify -> tokens
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models.auth import RefreshToken
from app.db.models.user import User
from app.schemas.auth import AuthResult, LoginIn, RegisterIn
from app.services import otp_service
from app.services.user_service import serialize_me
from app.utils.phone import looks_like_phone, to_e164


# ── helpers ────────────────────────────────────────────────────────────────
async def _get_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip()
    if looks_like_phone(ident):
        e164 = to_e164(ident)
        if not e164:
            return None
        res = await db.execute(select(User).where(User.phone == e164))
        return res.scalar_one_or_none()
    res = await db.execute(
        select(User).where(or_(User.email == ident.lower(), User.username == ident))
    )
    return res.scalar_one_or_none()


def _profile_complete(user: User) -> bool:
    return bool(user.display_name and user.username)


async def _issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    device_name: str | None,
    platform: str | None,
    is_new_user: bool = False,
) -> AuthResult:
    access = create_access_token(str(user.id), locale=user.locale)
    refresh = create_refresh_token(str(user.id))
    payload = decode_token(refresh, expected_type="refresh")
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=payload["jti"],
            device_name=device_name,
            platform=platform,
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    )
    await db.flush()
    return AuthResult(
        access_token=access,
        refresh_token=refresh,
        user=await serialize_me(user),
        profile_complete=_profile_complete(user),
        is_new_user=is_new_user,
    )


# ── register ───────────────────────────────────────────────────────────────
async def register(
    db: AsyncSession, data: RegisterIn, *, locale: str
) -> tuple[User, str, str | None]:
    email = data.email.lower() if data.email else None
    phone = to_e164(data.phone) if data.phone else None

    if data.phone and not phone:
        raise ConflictError("errors.validation", status_code=422, code="invalid_phone")

    if email:
        exists = await db.execute(select(User.id).where(User.email == email))
        if exists.first():
            raise ConflictError("auth.email_taken", code="email_taken")
    if phone:
        exists = await db.execute(select(User.id).where(User.phone == phone))
        if exists.first():
            raise ConflictError("auth.phone_taken", code="phone_taken")

    user = User(
        email=email,
        phone=phone,
        password_hash=hash_password(data.password) if data.password else None,
        display_name=data.display_name,
        locale=data.locale or locale,
    )
    db.add(user)
    await db.flush()

    sent = await otp_service.request_otp(
        db,
        identifier=email or phone,  # type: ignore[arg-type]
        purpose="register",
        locale=user.locale,
        user_id=str(user.id),
    )
    return user, sent.channel, sent.dev_code


async def verify_registration(
    db: AsyncSession, *, identifier: str, code: str, locale: str,
    device_name: str | None = None, platform: str | None = None,
) -> AuthResult:
    ident = identifier.strip()
    e164 = to_e164(ident) if looks_like_phone(ident) else None
    lookup = e164 or ident.lower()

    await otp_service.verify_otp(identifier=lookup, purpose="register", code=code, locale=locale)

    user = await _get_by_identifier(db, lookup)
    if user is None:
        raise NotFoundError("user.not_found", code="user_not_found")

    if e164:
        user.phone_verified = True
    else:
        user.email_verified = True
    await db.flush()

    return await _issue_tokens(db, user, device_name=device_name, platform=platform)


# ── login ──────────────────────────────────────────────────────────────────
async def login(
    db: AsyncSession, data: LoginIn, *, device_name: str | None = None, platform: str | None = None
) -> AuthResult:
    user = await _get_by_identifier(db, data.identifier)
    if user is None or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("auth.invalid_credentials", code="invalid_credentials")
    if not user.is_active:
        raise UnauthorizedError("auth.account_disabled", code="account_disabled")
    if user.email and not user.email_verified and not user.phone_verified:
        raise UnauthorizedError("auth.account_unverified", code="account_unverified")
    return await _issue_tokens(db, user, device_name=device_name, platform=platform)


async def login_with_otp(
    db: AsyncSession, *, identifier: str, code: str, locale: str,
    device_name: str | None = None, platform: str | None = None,
) -> AuthResult:
    ident = identifier.strip()
    e164 = to_e164(ident) if looks_like_phone(ident) else None
    lookup = e164 or ident.lower()

    await otp_service.verify_otp(identifier=lookup, purpose="login", code=code, locale=locale)

    user = await _get_by_identifier(db, lookup)
    if user is None:
        raise UnauthorizedError("auth.invalid_credentials", code="invalid_credentials")
    if e164:
        user.phone_verified = True
    await db.flush()
    return await _issue_tokens(db, user, device_name=device_name, platform=platform)


# ── Auth par telephone, sans mot de passe (flux principal du mobile) ───────
async def phone_start(
    db: AsyncSession, *, phone: str, locale: str
) -> tuple[str, str | None]:
    """Normalise le numero, cree le compte s'il n'existe pas encore, envoie
    le code SMS. Retourne `(e164, dev_code)` — `dev_code` non nul uniquement
    en mode test (settings.otp_dev_echo)."""
    e164 = to_e164(phone)
    if not e164:
        raise ConflictError("errors.validation", status_code=422, code="invalid_phone")

    res = await db.execute(select(User).where(User.phone == e164))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(phone=e164, locale=locale)
        db.add(user)
        await db.flush()
    elif not user.is_active:
        raise UnauthorizedError("auth.account_disabled", code="account_disabled")

    sent = await otp_service.request_otp(
        db, identifier=e164, purpose="login", locale=user.locale, user_id=str(user.id)
    )
    return e164, sent.dev_code


async def phone_verify(
    db: AsyncSession, *, phone: str, code: str, locale: str,
    device_name: str | None = None, platform: str | None = None,
) -> AuthResult:
    e164 = to_e164(phone)
    if not e164:
        raise ConflictError("errors.validation", status_code=422, code="invalid_phone")

    await otp_service.verify_otp(identifier=e164, purpose="login", code=code, locale=locale)

    res = await db.execute(select(User).where(User.phone == e164))
    user = res.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError("auth.invalid_credentials", code="invalid_credentials")

    is_new = not user.phone_verified
    user.phone_verified = True
    await db.flush()
    return await _issue_tokens(
        db, user, device_name=device_name, platform=platform, is_new_user=is_new
    )


# ── refresh / logout ───────────────────────────────────────────────────────
async def refresh_tokens(db: AsyncSession, refresh_token: str) -> AuthResult:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.PyJWTError as e:
        raise UnauthorizedError("auth.refresh_invalid", code="refresh_invalid") from e

    jti = payload["jti"]
    res = await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    row = res.scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise UnauthorizedError("auth.refresh_invalid", code="refresh_invalid")

    row.revoked_at = datetime.now(UTC)  # rotation
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise UnauthorizedError()
    return await _issue_tokens(db, user, device_name=row.device_name, platform=row.platform)


async def logout(db: AsyncSession, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        return
    res = await db.execute(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    row = res.scalar_one_or_none()
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


# ── link phone / email a un compte existant ────────────────────────────────
async def link_phone(db: AsyncSession, user: User, *, phone: str, code: str, locale: str) -> User:
    e164 = to_e164(phone)
    if not e164:
        raise ConflictError("errors.validation", status_code=422, code="invalid_phone")
    await otp_service.verify_otp(identifier=e164, purpose="link_phone", code=code, locale=locale)
    exists = await db.execute(select(User.id).where(User.phone == e164, User.id != user.id))
    if exists.first():
        raise ConflictError("auth.phone_taken", code="phone_taken")
    user.phone = e164
    user.phone_verified = True
    await db.flush()
    return user


async def link_email(db: AsyncSession, user: User, *, email: str, code: str, locale: str) -> User:
    em = email.lower()
    await otp_service.verify_otp(identifier=em, purpose="link_email", code=code, locale=locale)
    exists = await db.execute(select(User.id).where(User.email == em, User.id != user.id))
    if exists.first():
        raise ConflictError("auth.email_taken", code="email_taken")
    user.email = em
    user.email_verified = True
    await db.flush()
    return user


# ── suppression de compte ─────────────────────────────────────────────────
async def delete_account(db: AsyncSession, user: User) -> None:
    """Supprime definitivement le compte. Toutes les donnees liees (messages,
    stories, groupes crees, cles E2E, contacts...) tombent via `ON DELETE
    CASCADE`. Irreversible."""
    # revoque tous les refresh tokens d'abord (sessions actives coupees)
    rows = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    await db.flush()
    await db.delete(user)
    await db.flush()
