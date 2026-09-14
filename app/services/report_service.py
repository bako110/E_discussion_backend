"""Signalement d'un profil utilisateur (façon WhatsApp « Signaler »)."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.report import UserReport
from app.db.models.user import User
from app.schemas.report import UserReportIn, UserReportOut
from app.services.user_service import get_user_or_404


async def report_user(
    db: AsyncSession, reporter: User, reported_id: uuid.UUID, data: UserReportIn
) -> UserReportOut:
    if reporter.id == reported_id:
        raise AppError("user.cannot_report_self", status_code=400, code="cannot_report_self")
    await get_user_or_404(db, reported_id)

    report = UserReport(
        reporter_id=reporter.id,
        reported_id=reported_id,
        reason=data.reason,
        details=data.details,
    )
    db.add(report)
    await db.flush()
    return UserReportOut.model_validate(report)
