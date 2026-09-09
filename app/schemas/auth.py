"""Schemas d'authentification — inscription/connexion par e-mail ET/OU telephone."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import TokenPair
from app.schemas.user import UserMe


# ── Inscription ─────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(None, description="E.164, ex +33612345678")
    password: str | None = Field(None, min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=80)
    locale: str = "fr"

    @model_validator(mode="after")
    def _at_least_one_identifier(self) -> RegisterIn:
        if not self.email and not self.phone:
            raise ValueError("email ou phone requis")
        # mot de passe obligatoire si inscription par e-mail
        if self.email and not self.password:
            raise ValueError("password requis pour une inscription par e-mail")
        return self


class RegisterOut(BaseModel):
    user_id: uuid.UUID
    verification_channel: str  # "email" | "sms"
    message: str


# ── Connexion ──────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    identifier: str = Field(..., description="e-mail, username ou numero E.164")
    password: str


class AuthResult(TokenPair):
    user: UserMe
    # false = compte tout juste cree par OTP telephone, il faut encore
    # renseigner display_name + username (ecran "profil" cote mobile).
    profile_complete: bool = True
    is_new_user: bool = False


# ── Auth par telephone (sans mot de passe) ────────────────────────────────
class PhoneStartIn(BaseModel):
    phone: str = Field(..., description="Numero au format E.164, ex +33612345678")


class PhoneStartOut(BaseModel):
    phone: str          # E.164 normalise, a re-afficher dans le modal de confirmation
    sent: bool = True
    resend_in: int = 30  # secondes avant de pouvoir renvoyer un code


class PhoneVerifyIn(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=8)


# ── OTP generique (e-mail ou telephone) — conserve pour la liaison ────────
class SendOtpIn(BaseModel):
    identifier: str = Field(..., description="e-mail ou numero E.164")
    purpose: str = Field("register", pattern=r"^(register|login|link_phone|link_email|reset_password)$")


class VerifyOtpIn(BaseModel):
    identifier: str
    code: str = Field(..., min_length=4, max_length=8)
    purpose: str = "register"


class RefreshIn(BaseModel):
    refresh_token: str


class LinkPhoneIn(BaseModel):
    phone: str
    code: str


class LinkEmailIn(BaseModel):
    email: EmailStr
    code: str
