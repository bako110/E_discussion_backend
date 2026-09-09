"""Dependances FastAPI communes — utilisateur courant, langue, pagination."""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.models.user import User
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_locale(request: Request) -> str:
    return getattr(request.state, "locale", "fr")


Locale = Annotated[str, Depends(get_locale)]


async def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if creds is None:
        raise UnauthorizedError()
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as e:
        raise UnauthorizedError("auth.token_expired", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise UnauthorizedError() from e

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError()

    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise UnauthorizedError()
    return user


async def get_current_active_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_active:
        raise ForbiddenError("auth.account_disabled", code="account_disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_active_user)]


class Pagination:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        limit: int = Query(30, ge=1, le=100),
    ) -> None:
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit


PageParams = Annotated[Pagination, Depends(Pagination)]
