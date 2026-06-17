from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
AIRPORTS_PATH = ROOT_DIR / "data" / "russian_airports.tsv"
CITY_GROUPS_PATH = ROOT_DIR / "data" / "city_groups.json"

POPULAR_ORIGIN_CODES = ["SVX", "MOW", "LED", "AER"]
POPULAR_DESTINATION_CODES = ["MOW", "LED", "AER", "KZN"]
EXCLUDED_AUTOCOMPLETE_CODES = {"ZIA"}
EXTRA_KEYWORDS = {
    "SVX": ("екатеринбург", "свердловск", "кольцово"),
    "LED": ("санкт-петербург", "петербург", "питер", "спб", "пулково"),
    "AER": ("сочи", "адлер"),
    "OVB": ("новосибирск", "толмачево", "толмачёво"),
    "MRV": ("минеральные воды", "минводы"),
    "KGD": ("калининград", "храброво"),
}


@dataclass(frozen=True)
class Location:
    label: str
    value: str
    type: str
    city: str
    keywords: tuple[str, ...]


def _normalise_text(value: str | None) -> str:
    return " ".join((value or "").replace("ё", "е").lower().split())


def _read_airport_rows() -> list[dict[str, str]]:
    with AIRPORTS_PATH.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _read_city_groups() -> dict[str, dict[str, object]]:
    with CITY_GROUPS_PATH.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _airport_label(row: dict[str, str]) -> str:
    city = row["Населённый_пункт"].removesuffix(", город").strip()
    name = row["Название_аэропорта"].strip()
    code = row["Код_ИАТА"].strip().upper()
    if city and name and name.lower() not in city.lower():
        return f"{city}, {name} — {code}"
    return f"{city or name} — {code}"


def _airport_keywords(row: dict[str, str]) -> tuple[str, ...]:
    code = row["Код_ИАТА"].strip().upper()
    values = [
        code,
        row["Внутр._код"],
        row["Населённый_пункт"],
        row["Регион"],
        row["Название_аэропорта"],
        *EXTRA_KEYWORDS.get(code, ()),
    ]
    return tuple({keyword for value in values if (keyword := _normalise_text(value))})


@lru_cache(maxsize=1)
def get_locations() -> tuple[Location, ...]:
    locations: list[Location] = []
    rows = _read_airport_rows()
    by_code = {row["Код_ИАТА"].strip().upper(): row for row in rows if row["Код_ИАТА"].strip()}

    priority_airports: list[str] = []
    for code, group in _read_city_groups().items():
        city = str(group["ru"])
        airports = [airport for airport in group.get("airports", []) if isinstance(airport, str)]
        priority_airports.extend(airports)
        keywords = tuple({_normalise_text(value) for value in [city, code, *group.get("keywords", []), *airports] if value})
        locations.append(Location(f"{city} — все аэропорты — {code}", code, "city", city, keywords))

    added_codes: set[str] = set()
    for code in priority_airports:
        row = by_code.get(code)
        if row and code not in EXCLUDED_AUTOCOMPLETE_CODES:
            city = row["Населённый_пункт"].removesuffix(", город").strip()
            locations.append(Location(_airport_label(row), code, "airport", city, _airport_keywords(row)))
            added_codes.add(code)

    for code, row in by_code.items():
        if code in added_codes:
            continue
        if code in EXCLUDED_AUTOCOMPLETE_CODES:
            continue
        city = row["Населённый_пункт"].removesuffix(", город").strip()
        locations.append(Location(_airport_label(row), code, "airport", city, _airport_keywords(row)))

    return tuple(locations)


def _popular(codes: list[str]) -> list[tuple[str, str]]:
    labels = {location.value: location.label for location in get_locations()}
    return [(labels[code], code) for code in codes if code in labels]


def search_locations(query: str, limit: int = 10) -> list[dict[str, str]]:
    q = _normalise_text(query)
    if not q:
        matches = get_locations()[:limit]
    else:
        matches = [
            loc for loc in get_locations()
            if q in _normalise_text(loc.label) or any(q in keyword for keyword in loc.keywords)
        ][:limit]
    return [
        {"label": loc.label, "value": loc.value, "type": loc.type, "city": loc.city}
        for loc in matches
    ]


def get_location(value: str | None) -> Location | None:
    code = (value or "").strip().upper()
    if not code:
        return None
    for location in get_locations():
        if location.value.upper() == code:
            return location
    return None


def route_code_for_airport(airport_code: str | None) -> str | None:
    code = (airport_code or "").strip().upper()
    if not code:
        return None
    for group_code, group in _read_city_groups().items():
        airports = [airport.upper() for airport in group.get("airports", []) if isinstance(airport, str)]
        if code in airports:
            return group_code.upper()
    return code


def city_name_for_code(code: str | None) -> str | None:
    location = get_location(code)
    if not location:
        return None
    return location.city or location.label


POPULAR_ORIGINS = _popular(POPULAR_ORIGIN_CODES)
POPULAR_DESTINATIONS = _popular(POPULAR_DESTINATION_CODES)
