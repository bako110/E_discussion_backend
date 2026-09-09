"""Router media — upload de fichiers (images, videos, audio, avatars).

`POST /api/v1/media/upload` (multipart/form-data, champ `file`). Renvoie l'URL
publique + une miniature (image/video) + les metadonnees utiles au client
(story.media_url, group.avatar_url, user.avatar_url, message.attachment_url…).
"""
from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.api.deps import CurrentUser
from app.schemas.media import MediaOut
from app.services import media_service

router = APIRouter()


@router.post("/upload", response_model=MediaOut)
async def upload(current_user: CurrentUser, file: UploadFile = File(...)):
    result = await media_service.save_upload(file)
    return MediaOut(**result.as_dict())
