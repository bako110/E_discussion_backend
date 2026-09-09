"""Upload de medias (images, videos, audio, documents, avatars) sur disque local.

Ecrit sous `<MEDIA_ROOT>/<yyyy>/<mm>/<uuid>.<ext>`, servi en statique sous
`<MEDIA_URL_PREFIX>`. Traitement :
  - image : re-encodage + redimensionnement (cote max IMAGE_MAX_DIM) + miniature ;
  - video : copie brute + miniature via ffmpeg (1re frame) si dispo ;
  - audio : copie brute, duree lue via ffprobe si dispo ;
  - file  : copie brute (PDF, docs, archives…), aucun traitement.

Aucune dependance dure a ffmpeg : si le binaire est absent, on saute la
miniature video / la duree, sans echouer.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.errors import AppError

# extension -> categorie
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".3gp", ".mkv"}
_AUDIO_EXT = {".m4a", ".mp3", ".aac", ".ogg", ".opus", ".wav", ".amr"}
# documents joints a une conversation (aucun traitement, copie brute)
_FILE_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf",
    ".csv", ".odt", ".ods", ".odp", ".zip", ".rar", ".7z", ".gz", ".tar",
    ".epub",
}
_FILE_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/rtf",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/gzip",
    "application/x-tar",
    "application/epub+zip",
    "text/plain",
    "text/csv",
    "text/rtf",
}

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


class MediaResult:
    def __init__(
        self,
        *,
        url: str,
        media_type: str,
        thumbnail_url: str | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_sec: float | None = None,
        size: int = 0,
    ) -> None:
        self.url = url
        self.media_type = media_type
        self.thumbnail_url = thumbnail_url
        self.width = width
        self.height = height
        self.duration_sec = duration_sec
        self.size = size

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "media_type": self.media_type,
            "thumbnail_url": self.thumbnail_url,
            "width": self.width,
            "height": self.height,
            "duration_sec": self.duration_sec,
            "size": self.size,
        }


def _root() -> Path:
    p = Path(settings.MEDIA_ROOT)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _public_url(rel_path: str) -> str:
    prefix = settings.MEDIA_URL_PREFIX.rstrip("/")
    rel = rel_path.replace("\\", "/").lstrip("/")
    path = f"{prefix}/{rel}"
    base = settings.MEDIA_PUBLIC_BASE.rstrip("/")
    return f"{base}{path}" if base else path


def _categorize(ext: str, content_type: str | None) -> str:
    ext = ext.lower()
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    if ext in _FILE_EXT:
        return "file"
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    if ct in _FILE_CONTENT_TYPES:
        return "file"
    raise AppError("media.unsupported_type", status_code=415, code="unsupported_media")


def _ffmpeg() -> str | None:
    return shutil.which(settings.FFMPEG_BIN)


def _ffprobe() -> str | None:
    # ffprobe est generalement installe a cote de ffmpeg
    fp = shutil.which("ffprobe")
    if fp:
        return fp
    ff = _ffmpeg()
    if ff:
        cand = Path(ff).with_name("ffprobe" + Path(ff).suffix)
        if cand.exists():
            return str(cand)
    return None


def _probe_duration(path: Path) -> float | None:
    fp = _ffprobe()
    if not fp:
        return None
    try:
        out = subprocess.run(  # noqa: S603
            [
                fp, "-v", "quiet", "-print_format", "json",
                "-show_format", str(path),
            ],
            capture_output=True, text=True, timeout=20, check=False,
        )
        data = json.loads(out.stdout or "{}")
        dur = data.get("format", {}).get("duration")
        return round(float(dur), 2) if dur else None
    except Exception:
        return None


def _video_thumbnail(src: Path, dst: Path) -> bool:
    ff = _ffmpeg()
    if not ff:
        return False
    try:
        subprocess.run(  # noqa: S603
            [
                ff, "-y", "-ss", "0.5", "-i", str(src),
                "-frames:v", "1", "-vf",
                f"scale='min({settings.THUMB_MAX_DIM},iw)':-2",
                str(dst),
            ],
            capture_output=True, timeout=30, check=False,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        return False


def _process_image(src: Path, out_dir: Path, stem: str) -> tuple[str, str, int, int]:
    """Re-encode + redimensionne + genere une miniature. Retourne
    (rel_image, rel_thumb, width, height).

    `src` est le fichier brut deja ecrit sous `<stem><ext-original>` ; l'image
    traitee est ecrite sous `<stem>.jpg`/`.png` et la miniature sous
    `<stem>_thumb.jpg`. On lit tout en memoire d'abord pour pouvoir supprimer
    `src` sans conflit de verrou (Windows).
    """
    with Image.open(src) as opened:
        im = ImageOps.exif_transpose(opened)
        im.load()  # force le decodage complet avant de fermer `opened`

    has_alpha = im.mode in ("RGBA", "LA", "P")
    fmt = "PNG" if has_alpha else "JPEG"
    ext = ".png" if has_alpha else ".jpg"
    if not has_alpha and im.mode != "RGB":
        im = im.convert("RGB")

    full = im.copy()
    full.thumbnail((settings.IMAGE_MAX_DIM, settings.IMAGE_MAX_DIM), Image.LANCZOS)
    img_path = out_dir / f"{stem}{ext}"
    save_kw = {"quality": 85, "optimize": True} if fmt == "JPEG" else {"optimize": True}
    full.save(img_path, fmt, **save_kw)
    w, h = full.size

    thumb = im.copy()
    thumb.thumbnail((settings.THUMB_MAX_DIM, settings.THUMB_MAX_DIM), Image.LANCZOS)
    if thumb.mode != "RGB":
        thumb = thumb.convert("RGB")
    thumb_path = out_dir / f"{stem}_thumb.jpg"
    thumb.save(thumb_path, "JPEG", quality=80, optimize=True)

    # supprime le brut UNIQUEMENT s'il differe de l'image traitee (extension
    # d'origine != .jpg/.png). Sinon `img_path` EST le fichier qu'on garde.
    if src.resolve() != img_path.resolve():
        src.unlink(missing_ok=True)
    return img_path.name, thumb_path.name, w, h


async def save_upload(file: UploadFile) -> MediaResult:
    raw = await file.read()
    size = len(raw)
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if size == 0:
        raise AppError("media.empty_file", status_code=422, code="empty_file")
    if size > max_bytes:
        raise AppError(
            "media.too_large", status_code=413, code="file_too_large",
            params={"max_mb": settings.MAX_UPLOAD_MB},
        )

    orig_name = file.filename or "upload"
    ext = Path(orig_name).suffix.lower()
    if not ext:
        ext = _CONTENT_TYPE_EXT.get((file.content_type or "").lower(), "")
    category = _categorize(ext, file.content_type)
    if not ext:
        ext = {"image": ".jpg", "video": ".mp4", "audio": ".m4a", "file": ".bin"}[category]

    now = datetime.now(UTC)
    out_dir = _root() / f"{now:%Y}" / f"{now:%m}"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex
    rel_dir = f"{now:%Y}/{now:%m}"

    tmp_path = out_dir / f"{stem}{ext}"
    tmp_path.write_bytes(raw)

    # le traitement (Pillow / ffmpeg) est bloquant -> thread
    def _work() -> MediaResult:
        if category == "image":
            img_name, thumb_name, w, h = _process_image(tmp_path, out_dir, stem)
            return MediaResult(
                url=_public_url(f"{rel_dir}/{img_name}"),
                thumbnail_url=_public_url(f"{rel_dir}/{thumb_name}"),
                media_type="image",
                width=w, height=h, size=size,
            )

        if category == "video":
            thumb_name = f"{stem}_thumb.jpg"
            thumb_ok = _video_thumbnail(tmp_path, out_dir / thumb_name)
            return MediaResult(
                url=_public_url(f"{rel_dir}/{stem}{ext}"),
                thumbnail_url=_public_url(f"{rel_dir}/{thumb_name}") if thumb_ok else None,
                media_type="video",
                duration_sec=_probe_duration(tmp_path),
                size=size,
            )

        if category == "audio":
            return MediaResult(
                url=_public_url(f"{rel_dir}/{stem}{ext}"),
                media_type="audio",
                duration_sec=_probe_duration(tmp_path),
                size=size,
            )

        # file : document brut, aucun traitement
        return MediaResult(
            url=_public_url(f"{rel_dir}/{stem}{ext}"),
            media_type="file",
            size=size,
        )

    return await asyncio.to_thread(_work)
