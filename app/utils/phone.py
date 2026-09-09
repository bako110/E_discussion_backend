"""Normalisation des numeros de telephone en E.164."""
from __future__ import annotations

import phonenumbers


def to_e164(raw: str, default_region: str | None = None) -> str | None:
    """Retourne le numero en E.164 (`+33612345678`) ou None si invalide."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def looks_like_phone(value: str) -> bool:
    v = value.strip()
    return v.startswith("+") or v.replace(" ", "").replace("-", "").isdigit()
