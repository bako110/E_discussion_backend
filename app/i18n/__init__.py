"""i18n backend — chargement des catalogues JSON + resolution de cle.

Usage :
    from app.i18n import translate
    translate("errors.not_found", "en")
    translate("otp.sms_body", "fr", code="123456")

La langue effective d'une requete est posee sur `request.state.locale` par
`LocaleMiddleware` (voir app/core/middleware.py) a partir de `Accept-Language`.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

_LOCALES_DIR = Path(__file__).parent / "locales"


@lru_cache
def _catalog(locale: str) -> dict[str, Any]:
    path = _LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _lookup(catalog: dict[str, Any], dotted_key: str) -> str | None:
    node: Any = catalog
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def normalize_locale(raw: str | None) -> str:
    """`fr-FR,fr;q=0.9,en;q=0.8` -> `fr` si supporte, sinon defaut."""
    if not raw:
        return settings.DEFAULT_LOCALE
    first = raw.split(",")[0].strip().lower()
    lang = first.split("-")[0].split(";")[0]
    return lang if lang in settings.supported_locales else settings.DEFAULT_LOCALE


def translate(key: str, locale: str | None = None, /, **params: Any) -> str:
    """Resout `key` dans la langue demandee, avec repli sur la langue par
    defaut puis sur la cle brute. `params` alimente un `str.format`."""
    loc = normalize_locale(locale)
    text = _lookup(_catalog(loc), key)
    if text is None and loc != settings.DEFAULT_LOCALE:
        text = _lookup(_catalog(settings.DEFAULT_LOCALE), key)
    if text is None:
        return key
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError):
        return text


def available_locales() -> list[str]:
    return list(settings.supported_locales)
