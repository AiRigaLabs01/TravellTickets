from urllib.parse import urlencode

from app.config import YANDEX_TRAVEL_BASE


YANDEX_CITY_IDS = {
    "MOW": "c213",  # Москва
    "SVO": "c213",
    "DME": "c213",
    "VKO": "c213",
    "ZIA": "c213",
    "SVX": "c54",  # Екатеринбург
}


def _yandex_id(code: str) -> str:
    code = (code or "").upper().strip()
    return YANDEX_CITY_IDS.get(code, code)


def build_yandex_travel_url(origin: str, destination: str, departure_date: str, return_date: str | None = None) -> str:
    """Build a Yandex Travel deeplink with Yandex city identifiers."""
    params = {
        "adult_seats": "1",
        "children_seats": "0",
        "fromId": _yandex_id(origin),
        "infant_seats": "0",
        "klass": "economy",
        "oneway": "2" if return_date else "1",
        "salesChannel": "B2C",
        "toId": _yandex_id(destination),
        "when": departure_date,
    }
    if return_date:
        params["return_date"] = return_date
    return f"{YANDEX_TRAVEL_BASE}?{urlencode(params)}"
