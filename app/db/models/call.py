"""Appels 1-to-1 (WebRTC via LiveKit self-hosted).

Le serveur LiveKit relaie les flux media ; ce backend ne fait que :
  - creer la room + generer les tokens JWT d'acces,
  - relayer la signalisation d'appel (sonnerie/accept/reject/hangup) via WS,
  - historiser l'appel (statut, duree).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class CallType(str, enum.Enum):
    voice = "voice"
    video = "video"


class CallDirection(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"
    missed = "missed"


class CallStatus(str, enum.Enum):
    ringing = "ringing"      # l'appel sonne chez le callee
    active = "active"        # les deux parties sont connectees
    ended = "ended"          # termine normalement (au moins un decroche)
    missed = "missed"        # le callee n'a pas repondu / a raccroche avant
    rejected = "rejected"    # le callee a explicitement refuse
    cancelled = "cancelled"  # le caller a annule avant reponse
    failed = "failed"        # erreur technique (connexion impossible)


class CallLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "call_logs"

    caller_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    callee_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    call_type: Mapped[CallType] = mapped_column(Enum(CallType), nullable=False)
    # 'direction' garde du sens cote client (colonne conservee pour compat).
    direction: Mapped[CallDirection] = mapped_column(
        Enum(CallDirection), default=CallDirection.outgoing, nullable=False
    )
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus), default=CallStatus.ringing, nullable=False
    )
    # nom de la room LiveKit (unique par appel)
    room_name: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    # cle E2EE partagee (base64) — generee par le caller, transmise au callee
    # via le canal chiffre du WS ; le serveur ne l'utilise pas.
    e2ee_key: Mapped[str | None] = mapped_column(String(128))

    duration_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
