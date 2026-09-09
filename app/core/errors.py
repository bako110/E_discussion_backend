"""Exceptions applicatives + handlers FastAPI.

Chaque `AppError` porte une cle i18n (`message_key`) et non un texte fige :
le handler traduit selon l'en-tete `Accept-Language` de la requete.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.i18n import translate

log = get_logger(__name__)


class AppError(Exception):
    """Erreur metier connue. `message_key` est resolue via i18n."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    message_key: str = "errors.generic"
    code: str = "app_error"

    def __init__(
        self,
        message_key: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.message_key = message_key or self.message_key
        self.status_code = status_code or self.status_code
        self.code = code or self.code
        self.params = params or {}
        super().__init__(self.message_key)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    message_key = "errors.not_found"
    code = "not_found"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    message_key = "errors.unauthorized"
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    message_key = "errors.forbidden"
    code = "forbidden"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    message_key = "errors.conflict"
    code = "conflict"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message_key = "errors.rate_limited"
    code = "rate_limited"


def _locale_of(request: Request) -> str:
    return getattr(request.state, "locale", None) or "fr"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        locale = _locale_of(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": {
                    "code": exc.code,
                    "message": translate(exc.message_key, locale, **exc.params),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        locale = _locale_of(request)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": translate("errors.validation", locale),
                    "fields": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception", path=request.url.path)
        locale = _locale_of(request)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": {
                    "code": "internal_error",
                    "message": translate("errors.internal", locale),
                }
            },
        )
