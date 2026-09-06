from urllib.parse import urlencode

from app.config import YANDEX_TRAVEL_BASE


YANDEX_CITY_IDS = {
    "MOW": "c213",
    "SVO": "c213",
    "DME": "c213",
    "VKO": "c213",
    "SVX": "c54",
}


def _yandex_id(code: str) -> str:
    code = (code or "").upper().strip()
    return YANDEX_CITY_IDS.get(code, code)


def build_yandex_travel_url(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adult_seats: int = 1,
    children_seats: int = 0,
    infant_seats: int = 0,
) -> str:
    """Build a Yandex Travel deeplink with Yandex city identifiers."""
    params = {
        "adult_seats": max(int(adult_seats or 1), 1),
        "children_seats": max(int(children_seats or 0), 0),
        "fromId": _yandex_id(origin),
        "infant_seats": max(int(infant_seats or 0), 0),
        "klass": "economy",
        "oneway": "2" if return_date else "1",
        "salesChannel": "B2C",
        "toId": _yandex_id(destination),
        "when": departure_date,
    }
    if return_date:
        params["return_date"] = return_date
    return f"{YANDEX_TRAVEL_BASE}?{urlencode(params)}"


def build_yandex_travel_url_for_route(route) -> str:
    return build_yandex_travel_url(
        route.origin,
        route.destination,
        route.departure_date,
        route.return_date if getattr(route, "trip_type", "oneway") == "roundtrip" else None,
        getattr(route, "adult_seats", 1),
        getattr(route, "children_seats", 0),
        getattr(route, "infant_seats", 0),
    )
