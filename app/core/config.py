"""Configuration centrale — chargee depuis l'environnement via pydantic-settings.

Toute la config de l'app passe par l'objet `settings` (import unique). Aucune
lecture directe de `os.environ` ailleurs dans le code.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_NAME: str = "E-discussion"
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    # CSV en .env (ex: "http://a,http://b") — expose en liste via la property
    # `cors_origins`. On garde un `str` brut pour eviter que pydantic-settings
    # tente un parse JSON du champ.
    CORS_ORIGINS: str = ""

    # ── i18n ───────────────────────────────────────────────────────────────
    DEFAULT_LOCALE: str = "fr"
    SUPPORTED_LOCALES: str = "fr,en"

    # ── PostgreSQL ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://ediscussion:ediscussion@localhost:5432/ediscussion"
    SQL_ECHO: bool = False  # true = log tout le SQL (tres verbeux)

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ────────────────────────────────────────────────────────────────
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 60

    # ── OTP ────────────────────────────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    # DEV UNIQUEMENT : renvoie le code OTP dans la reponse de l'API (pour
    # tester sans SMS). REFUSE si ENV == production. A mettre a False des que
    # l'envoi SMS reel est branche.
    OTP_DEV_ECHO: bool = False

    # ── Twilio ─────────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_VERIFY_SERVICE_SID: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # ── Email ──────────────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "E-discussion <no-reply@ediscussion.app>"

    # ── Media / uploads ────────────────────────────────────────────────────
    # Repertoire disque ou sont ecrits les fichiers uploades (images, videos,
    # audio, avatars). Servi en statique sous MEDIA_URL_PREFIX.
    MEDIA_ROOT: str = "media"
    MEDIA_URL_PREFIX: str = "/media"
    # Base publique pour construire les URLs absolues renvoyees au client.
    # Vide -> URL relative (le client prefixe avec API_BASE_URL).
    MEDIA_PUBLIC_BASE: str = ""
    MAX_UPLOAD_MB: int = 80
    IMAGE_MAX_DIM: int = 1600      # cote max apres redimensionnement
    THUMB_MAX_DIM: int = 320       # cote max des miniatures
    FFMPEG_BIN: str = "ffmpeg"    # binaire ffmpeg (miniature video) — optionnel

    # ── Cloudinary ─────────────────────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # ── FCM ────────────────────────────────────────────────────────────────
    FCM_CREDENTIALS_FILE: str = "firebase-service-account.json"

    # ── LiveKit (appels WebRTC — SFU auto-heberge) ───────────────────────
    # URL cote CLIENT (wss://) transmise a l'app pour rejoindre les rooms.
    LIVEKIT_URL: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    # duree de validite d'un token d'acces a une room (secondes)
    LIVEKIT_TOKEN_TTL: int = 3600
    # timeout de sonnerie : au-dela, l'appel bascule en "missed" (secondes)
    CALL_RING_TIMEOUT: int = 45

    @property
    def calls_enabled(self) -> bool:
        return bool(self.LIVEKIT_URL and self.LIVEKIT_API_KEY and self.LIVEKIT_API_SECRET)

    # ── Derived ────────────────────────────────────────────────────────────
    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return self._csv(self.CORS_ORIGINS)

    @property
    def supported_locales(self) -> list[str]:
        return self._csv(self.SUPPORTED_LOCALES) or ["fr"]

    @property
    def is_prod(self) -> bool:
        return self.ENV == "production"

    @property
    def otp_dev_echo(self) -> bool:
        """Echo du code OTP autorise seulement hors production."""
        return self.OTP_DEV_ECHO and self.ENV != "production"

    @property
    def sync_database_url(self) -> str:
        """URL synchrone pour Alembic (psycopg/asyncpg -> sync)."""
        return self.DATABASE_URL.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
