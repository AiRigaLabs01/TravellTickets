from app.config import YANDEX_TRAVEL_BASE


def build_yandex_travel_url(origin: str, destination: str, departure_date: str) -> str:
    """
    Build a Yandex Travel search URL.

    TODO: The exact deeplink format for Yandex Travel may change.
    The current template uses city codes (c{IATA}) as a best-effort approach.
    If precise deeplink format becomes known, update this function accordingly.
    For now this URL opens a search page — the exact flight is not pre-selected.
    """
    date_fmt = departure_date.replace("-", "")
    url = (
        f"{YANDEX_TRAVEL_BASE}"
        f"?fromId=c{origin}&toId=c{destination}&when={date_fmt}"
    )
    return url
