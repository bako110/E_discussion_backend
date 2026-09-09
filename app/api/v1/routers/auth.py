"""Router auth — inscription/connexion par e-mail ET/OU telephone, OTP, refresh."""
from __future__ import annotations

from fastapi import APIRouter, Header, status

from app.api.deps import CurrentUser, DbSession, Locale
from app.schemas.auth import (
    AuthResult,
    LinkEmailIn,
    LinkPhoneIn,
    LoginIn,
    PhoneStartIn,
    PhoneStartOut,
    PhoneVerifyIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    SendOtpIn,
    VerifyOtpIn,
)
from app.schemas.common import Message
from app.schemas.user import UserMe
from app.services import account_export_service, auth_service, otp_service
from app.services.user_service import serialize_me
from app.utils.phone import looks_like_phone, to_e164

router = APIRouter()


# ── Flux principal du mobile : telephone, sans mot de passe ───────────────
@router.post("/phone/start", response_model=PhoneStartOut)
async def phone_start(body: PhoneStartIn, db: DbSession, locale: Locale):
    """Etape 1 : le client a saisi pays + numero et confirme dans un modal.
    On normalise en E.164, on cree le compte si besoin, et on envoie le code
    par SMS (affiche dans les logs si Twilio n'est pas configure)."""
    e164 = await auth_service.phone_start(db, phone=body.phone, locale=locale)
    return PhoneStartOut(phone=e164, sent=True, resend_in=30)


@router.post("/phone/verify", response_model=AuthResult)
async def phone_verify(
    body: PhoneVerifyIn,
    db: DbSession,
    locale: Locale,
    x_device_name: str | None = Header(default=None),
    x_platform: str | None = Header(default=None),
):
    """Etape 2 : verifie le code. Renvoie les tokens + `profile_complete`
    (false -> le mobile affiche l'ecran nom complet + username)."""
    return await auth_service.phone_verify(
        db,
        phone=body.phone,
        code=body.code,
        locale=locale,
        device_name=x_device_name,
        platform=x_platform,
    )


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    db: DbSession,
    locale: Locale,
):
    user, channel = await auth_service.register(db, body, locale=locale)
    return RegisterOut(
        user_id=user.id,
        verification_channel=channel,
        message="verification code sent",
    )


@router.post("/verify-registration", response_model=AuthResult)
async def verify_registration(
    body: VerifyOtpIn,
    db: DbSession,
    locale: Locale,
    x_device_name: str | None = Header(default=None),
    x_platform: str | None = Header(default=None),
):
    return await auth_service.verify_registration(
        db,
        identifier=body.identifier,
        code=body.code,
        locale=locale,
        device_name=x_device_name,
        platform=x_platform,
    )


@router.post("/login", response_model=AuthResult)
async def login(
    body: LoginIn,
    db: DbSession,
    x_device_name: str | None = Header(default=None),
    x_platform: str | None = Header(default=None),
):
    return await auth_service.login(db, body, device_name=x_device_name, platform=x_platform)


@router.post("/otp/send", response_model=Message)
async def send_otp(body: SendOtpIn, db: DbSession, locale: Locale):
    ident = body.identifier.strip()
    lookup = to_e164(ident) if looks_like_phone(ident) else ident.lower()
    if not lookup:
        return Message(message="invalid identifier")
    await otp_service.request_otp(db, identifier=lookup, purpose=body.purpose, locale=locale)
    return Message(message="OTP sent")


@router.post("/otp/verify", response_model=AuthResult)
async def verify_otp_login(
    body: VerifyOtpIn,
    db: DbSession,
    locale: Locale,
    x_device_name: str | None = Header(default=None),
    x_platform: str | None = Header(default=None),
):
    """Connexion par OTP (SMS/e-mail) sans mot de passe — purpose=login."""
    return await auth_service.login_with_otp(
        db,
        identifier=body.identifier,
        code=body.code,
        locale=locale,
        device_name=x_device_name,
        platform=x_platform,
    )


@router.post("/refresh", response_model=AuthResult)
async def refresh(body: RefreshIn, db: DbSession):
    return await auth_service.refresh_tokens(db, body.refresh_token)


@router.post("/logout", response_model=Message)
async def logout(body: RefreshIn | None, db: DbSession):
    await auth_service.logout(db, body.refresh_token if body else None)
    return Message(message="ok")


@router.get("/me", response_model=UserMe)
async def me(current_user: CurrentUser):
    return await serialize_me(current_user)


@router.get("/me/export")
async def export_my_data(current_user: CurrentUser, db: DbSession):
    """Archive JSON de toutes mes donnees (portabilite / RGPD)."""
    return await account_export_service.build_export(db, current_user)


@router.delete("/me", response_model=Message, status_code=status.HTTP_200_OK)
async def delete_my_account(current_user: CurrentUser, db: DbSession):
    """Supprime DEFINITIVEMENT le compte et toutes les donnees liees.
    Irreversible — le client doit demander une double confirmation."""
    await auth_service.delete_account(db, current_user)
    return Message(message="account_deleted")


@router.post("/phone/link", response_model=UserMe)
async def link_phone(body: LinkPhoneIn, current_user: CurrentUser, db: DbSession, locale: Locale):
    user = await auth_service.link_phone(
        db, current_user, phone=body.phone, code=body.code, locale=locale
    )
    return await serialize_me(user)


@router.post("/email/link", response_model=UserMe)
async def link_email(body: LinkEmailIn, current_user: CurrentUser, db: DbSession, locale: Locale):
    user = await auth_service.link_email(
        db, current_user, email=body.email, code=body.code, locale=locale
    )
    return await serialize_me(user)
