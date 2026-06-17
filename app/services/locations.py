import re

from app.city_codes import resolve_iata
from app.locations import search_locations

IATA_RE = re.compile(r"\b([A-Z]{3})\b", re.IGNORECASE)


def resolve_location_code(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for item in search_locations(raw, limit=20):
        label = item["label"]
        code = item["value"].upper()
        if raw == label or raw.upper() == code:
            return code
    match = IATA_RE.search(raw)
    if match:
        code = resolve_iata(match.group(1))
        if len(code) == 3 and code.isalpha() and code.isascii():
            return code.upper()
    code = resolve_iata(raw)
    return code.upper() if len(code) == 3 and code.isalpha() and code.isascii() else None


def location_choices(value: str | None, limit: int = 6) -> list[tuple[str, str]]:
    return [(item["label"], item["value"]) for item in search_locations(value or "", limit=limit)]


def should_offer_location_choices(value: str | None) -> bool:
    raw = (value or "").strip()
    if len(raw) == 3 and raw.isalpha():
        return False
    choices = location_choices(raw)
    if len(choices) <= 1:
        return False
    return not any(raw == label or raw.upper() == code.upper() for label, code in choices)
