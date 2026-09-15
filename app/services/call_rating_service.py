"""Notation post-appel — un seul avis par (appel, utilisateur) : un second
envoi remplace le premier plutôt que d'empiler des doublons."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.db.models.call import CallLog
from app.db.models.call_rating import CallRating
from app.db.models.user import User
from app.schemas.call_rating import CallRatingIn, CallRatingOut


async def rate_call(
    db: AsyncSession, me: User, call_id: uuid.UUID, data: CallRatingIn
) -> CallRatingOut:
    call = await db.get(CallLog, call_id)
    if call is None:
        raise NotFoundError("calls.not_found", code="call_not_found")
    if me.id not in (call.caller_id, call.callee_id):
        raise ForbiddenError()

    existing = await db.scalar(
        select(CallRating).where(
            CallRating.call_id == call_id, CallRating.user_id == me.id
        )
    )
    if existing is not None:
        existing.call_score = data.call_score
        existing.app_score = data.app_score
        existing.comment = data.comment
        await db.flush()
        return CallRatingOut.model_validate(existing)

    rating = CallRating(
        call_id=call_id,
        user_id=me.id,
        call_score=data.call_score,
        app_score=data.app_score,
        comment=data.comment,
    )
    db.add(rating)
    await db.flush()
    return CallRatingOut.model_validate(rating)
