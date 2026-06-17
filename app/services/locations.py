import re
from dataclasses import dataclass

from app.city_codes import resolve_iata
from app.locations import get_location, route_code_for_airport, search_locations

IATA_RE = re.compile(r"\b([A-Z]{3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResolvedRouteLocation:
    code: str
    airport_code: str | None = None


def _resolved_from_code(code: str | None) -> ResolvedRouteLocation | None:
    normalized = (code or "").strip().upper()
    if not (len(normalized) == 3 and normalized.isalpha() and normalized.isascii()):
        return None
    location = get_location(normalized)
    if location and location.type == "airport":
        return ResolvedRouteLocation(route_code_for_airport(normalized) or normalized, normalized)
    return ResolvedRouteLocation(normalized, None)


def resolve_location_code(value: str | None) -> str | None:
    resolved = resolve_route_location(value)
    return resolved.code if resolved else None


def resolve_route_location(value: str | None) -> ResolvedRouteLocation | None:
    raw = (value or "").strip()
    if not raw:
        return None
    matches = search_locations(raw, limit=20)
    for item in matches:
        label = item["label"]
        code = item["value"].upper()
        if raw == label or raw.upper() == code:
            return _resolved_from_code(code)
    if len(matches) == 1:
        return _resolved_from_code(matches[0]["value"])
    match = IATA_RE.search(raw)
    if match:
        code = resolve_iata(match.group(1))
        resolved = _resolved_from_code(code)
        if resolved:
            return resolved
    code = resolve_iata(raw)
    return _resolved_from_code(code)


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
