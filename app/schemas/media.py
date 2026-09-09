"""Schemas media (upload de fichiers)."""
from __future__ import annotations

from pydantic import BaseModel


class MediaOut(BaseModel):
    url: str
    media_type: str  # 'image' | 'video' | 'audio' | 'file'
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    size: int = 0
