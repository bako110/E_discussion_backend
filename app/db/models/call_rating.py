"""Notation post-appel — qualité de l'appel + note de l'application, façon
prompt occasionnel (pas à chaque appel, voir cooldown côté client)."""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class CallRating(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "call_ratings"
    __table_args__ = (
        CheckConstraint("call_score BETWEEN 1 AND 5", name="ck_call_rating_call_score"),
        CheckConstraint(
            "app_score IS NULL OR app_score BETWEEN 1 AND 5", name="ck_call_rating_app_score"
        ),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("call_logs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    call_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # note de l'app proposee dans le meme prompt — facultative (l'utilisateur
    # peut noter l'appel sans noter l'app).
    app_score: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
