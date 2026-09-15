"""Notation post-appel — qualite de l'appel + note de l'app (facultative)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CallRatingIn(BaseModel):
    call_score: int = Field(ge=1, le=5)
    app_score: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class CallRatingOut(ORMModel):
    id: uuid.UUID
    call_id: uuid.UUID
    call_score: int
    app_score: int | None
    created_at: datetime
