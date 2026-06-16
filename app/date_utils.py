from datetime import datetime


RU_MONTHS_GENITIVE = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def parse_route_date(value: str | None) -> str | None:
    """Normalize user-entered route date to ISO YYYY-MM-DD."""
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def format_route_date(value: str | None) -> str:
    """Format ISO route date as DD.MM.YYYY for compact UI display."""
    iso = parse_route_date(value)
    if not iso:
        return value or "—"
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


def format_route_date_long(value: str | None) -> str:
    """Format ISO route date as '21 июня 2026' for Telegram messages."""
    iso = parse_route_date(value)
    if not iso:
        return value or "—"
    dt = datetime.strptime(iso, "%Y-%m-%d")
    return f"{dt.day} {RU_MONTHS_GENITIVE[dt.month]} {dt.year}"
