"""Stories (statuts ephemeres, 24h) — publication, vues, reactions.

Une story appartient a un auteur, expire 24h apres sa creation. Les autres
utilisateurs (contacts / personnes en conversation) peuvent la voir, y
reagir (emoji) et y repondre — la reponse est un `Message` normal dans la
conversation auteur<->repondeur, avec `story_id` renseigne pour afficher le
contexte "a repondu a votre story".
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class StoryMediaType(str, enum.Enum):
    text = "text"       # story texte (fond colore + legende)
    image = "image"
    video = "video"
    audio = "audio"     # piste audio + visuel (fond colore / image)
    voice = "voice"     # note vocale enregistree


class Story(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stories"
    __table_args__ = (
        # idempotence offline : un rejeu de l'outbox (retry apres reconnexion)
        # avec le meme client_id ne cree pas de doublon.
        Index("ix_stories_author_client", "author_id", "client_id", unique=True),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # id genere cote client (outbox) — permet de rejouer une publication
    # hors-ligne sans creer de doublon si le POST avait deja abouti.
    client_id: Mapped[str | None] = mapped_column(String(64))

    media_type: Mapped[StoryMediaType] = mapped_column(
        Enum(StoryMediaType), default=StoryMediaType.text, nullable=False
    )
    # URL du media principal (image/video) — null pour texte / voix pure
    media_url: Mapped[str | None] = mapped_column(String(1024))
    # legende (image/video/audio) ou contenu (story texte)
    caption: Mapped[str | None] = mapped_column(Text)
    # metadonnees d'affichage : couleur de fond, police, duree (s), miniature…
    background_color: Mapped[str | None] = mapped_column(String(16))
    font: Mapped[str | None] = mapped_column(String(32))
    duration_sec: Mapped[int] = mapped_column(default=5, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    # piste audio associee (media_type audio/voice) + nom affiche
    audio_url: Mapped[str | None] = mapped_column(String(1024))
    audio_name: Mapped[str | None] = mapped_column(String(120))
    # audience : 'everyone' (defaut) | 'contacts' — v1 simple
    audience: Mapped[str] = mapped_column(String(16), default="everyone", nullable=False)
    # renseigne quand cette story est un REPARTAGE d'une autre (façon
    # WhatsApp « Ajouter à mon statut ») — pointe vers la story d'origine.
    # SET NULL si l'originale est un jour purgée physiquement (aujourd'hui
    # seulement soft-delete via deleted_at, mais on protège quand meme).
    reshared_from_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("stories.id", ondelete="SET NULL")
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoryView(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Un enregistrement par (story, spectateur)."""

    __tablename__ = "story_views"
    __table_args__ = (
        UniqueConstraint("story_id", "viewer_id", name="uq_story_view"),
    )

    story_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("stories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )


class StoryReaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Reaction emoji a une story (une par utilisateur, remplacable)."""

    __tablename__ = "story_reactions"
    __table_args__ = (
        UniqueConstraint("story_id", "user_id", name="uq_story_reaction"),
    )

    story_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("stories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)


class StoryAudienceMode(str, enum.Enum):
    contacts = "contacts"                 # tous mes contacts
    contacts_except = "contacts_except"   # tous mes contacts SAUF la liste
    only = "only"                         # UNIQUEMENT la liste


class StoryAudienceEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Un contact listé pour la confidentialité des statuts d'un utilisateur.

    Sens selon `owner.story_audience_mode` :
      - `contacts_except` -> `target` est EXCLU,
      - `only`            -> `target` est le SEUL autorisé (avec les autres
        entrées),
      - `contacts`        -> les entrées sont ignorées.
    Évalué à l'affichage (liste courante), façon WhatsApp.
    """

    __tablename__ = "story_audience_entries"
    __table_args__ = (
        UniqueConstraint("owner_id", "target_id", name="uq_story_audience"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
