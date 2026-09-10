"""Schemas appels WebRTC (LiveKit self-hosted)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.call import CallStatus, CallType
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


class CallStartIn(BaseModel):
    callee_id: uuid.UUID
    call_type: CallType = CallType.voice
    # cle E2EE (base64) generee par l'appelant — relayee au callee via WS,
    # jamais utilisee par le serveur.
    e2ee_key: str | None = Field(None, max_length=128)


class CallOut(ORMModel):
    id: uuid.UUID
    caller_id: uuid.UUID
    callee_id: uuid.UUID
    call_type: CallType
    status: CallStatus
    room_name: str
    duration_sec: int = 0
    started_at: datetime
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    # rempli cote service : l'autre participant (pour l'affichage)
    peer: UserPublic | None = None


class CallStartOut(CallOut):
    """Reponse a POST /calls : inclut l'acces LiveKit pour l'appelant."""

    livekit_url: str
    token: str
    e2ee_key: str | None = None
    # le destinataire a-t-il un WebSocket actif ? l'appelant adapte sa
    # tonalite de retour d'appel (sonne normalement vs "indisponible").
    callee_online: bool = True


class CallTokenOut(BaseModel):
    """Reponse a POST /calls/{id}/token : acces LiveKit pour rejoindre."""

    livekit_url: str
    token: str
    room_name: str
    call_type: CallType
    e2ee_key: str | None = None
    peer: UserPublic | None = None


class CallEndIn(BaseModel):
    # raison optionnelle envoyee par le client
    reason: str | None = Field(None, pattern="^(hangup|rejected|cancelled|failed|missed)$")
