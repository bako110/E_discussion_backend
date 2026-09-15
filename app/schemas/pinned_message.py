"""Messages épinglés — 1-1 et groupe/chaîne."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

# durées d'épinglage proposées — None = indéterminé (jamais expiré tout seul)
PIN_DURATIONS: dict[str, int | None] = {
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
    "forever": None,
}


class PinMessageIn(BaseModel):
    message_id: uuid.UUID
    # slug parmi PIN_DURATIONS — défaut historique : indéterminé (comportement
    # d'avant l'ajout de cette fonctionnalité, personne n'est surpris).
    duration: str = Field("forever", pattern=r"^(24h|7d|30d|forever)$")


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
    expires_at: datetime | None = None
    message: PinnedMessagePreview | None = None
