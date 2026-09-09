"""Point d'entree FastAPI — E-discussion backend."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import LocaleMiddleware, RequestIdMiddleware
from app.db.redis import close_redis, init_redis
from app.i18n import available_locales
from app.services.ws_manager import manager

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", env=settings.ENV, locales=available_locales())
    # Teste Redis ; bascule sur un fallback memoire si indisponible (dev sans
    # Redis) — OTP, cooldown et presence continuent de fonctionner.
    await init_redis()
    yield
    await manager.shutdown()
    await close_redis()
    log.info("shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="E-discussion — messagerie 1-to-1 chiffree, e-mail + telephone.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LocaleMiddleware)
app.add_middleware(RequestIdMiddleware)

register_exception_handlers(app)

# Fichiers uploades (images / videos / audio / avatars) servis en statique.
_media_root = Path(settings.MEDIA_ROOT)
_media_root.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.MEDIA_URL_PREFIX,
    StaticFiles(directory=str(_media_root)),
    name="media",
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["System"])
async def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}


@app.get("/", tags=["System"])
async def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "docs": "/docs",
        "api": settings.API_V1_PREFIX,
        "locales": available_locales(),
    }
