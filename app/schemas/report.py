"""Signalement d'un profil utilisateur."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.report import ReportReason
from app.schemas.common import ORMModel


class UserReportIn(BaseModel):
    reason: ReportReason
    details: str | None = Field(None, max_length=1000)


class UserReportOut(ORMModel):
    id: uuid.UUID
    reported_id: uuid.UUID
    reason: ReportReason
    created_at: datetime
