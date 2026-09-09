"""Middlewares transverses — resolution de langue + request id."""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.i18n import normalize_locale


class LocaleMiddleware(BaseHTTPMiddleware):
    """Pose `request.state.locale` a partir de, par ordre de priorite :
    1. query param `?lang=`
    2. header `X-Lang`
    3. header `Accept-Language`
    Repli sur DEFAULT_LOCALE.
    """

    async def dispatch(self, request: Request, call_next):
        raw = (
            request.query_params.get("lang")
            or request.headers.get("x-lang")
            or request.headers.get("accept-language")
        )
        request.state.locale = normalize_locale(raw)
        response = await call_next(request)
        response.headers["Content-Language"] = request.state.locale
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response
