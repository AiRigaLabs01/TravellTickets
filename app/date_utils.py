from datetime import datetime, timezone
from zoneinfo import ZoneInfo


MSK_TZ = ZoneInfo("Europe/Moscow")

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


def to_msk(value: datetime | None) -> datetime | None:
    """Convert datetime to Moscow time. Naive datetimes are treated as UTC/server time."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK_TZ)


def format_msk_datetime(value: datetime | str | None) -> str:
    dt = to_msk(value) if not isinstance(value, str) else to_msk(value)
    if dt is None:
        return value if isinstance(value, str) and value else "—"
    return dt.strftime("%d.%m.%Y %H:%M МСК")


def format_msk_time(value: datetime | str | None) -> str:
    dt = to_msk(value) if not isinstance(value, str) else to_msk(value)
    if dt is None:
        return value if isinstance(value, str) and value else "—"
    return dt.strftime("%H:%M МСК")
