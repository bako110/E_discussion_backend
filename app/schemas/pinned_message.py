"""Messages épinglés — 1-1 et groupe/chaîne."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class PinMessageIn(BaseModel):
    message_id: uuid.UUID


class PinnedMessagePreview(BaseModel):
    """Aperçu du message épinglé — évite un aller-retour supplémentaire côté
    client pour afficher le bandeau (façon ReplyPreview)."""

    id: uuid.UUID
    type: str
    body: str
    sender_id: uuid.UUID


class PinnedMessageOut(ORMModel):
    id: uuid.UUID
    message_id: uuid.UUID
    pinned_by: uuid.UUID
    created_at: datetime
    message: PinnedMessagePreview | None = None
