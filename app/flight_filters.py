from datetime import datetime
from typing import Any


def _parse_time(time_str: str | None) -> tuple[int, int] | None:
    """Parse HH:MM into (hour, minute)."""
    if not time_str:
        return None
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


def _time_in_range(dt: datetime | None, from_str: str | None, to_str: str | None) -> bool:
    if dt is None:
        return True
    from_t = _parse_time(from_str)
    to_t = _parse_time(to_str)
    if from_t is None and to_t is None:
        return True
    h, m = dt.hour, dt.minute
    total = h * 60 + m
    if from_t is not None:
        from_total = from_t[0] * 60 + from_t[1]
        if total < from_total:
            return False
    if to_t is not None:
        to_total = to_t[0] * 60 + to_t[1]
        if total > to_total:
            return False
    return True


def _split_codes(value: str | None) -> list[str]:
    if not value:
        return []
    return [c.strip().upper() for c in value.split(",") if c.strip()]


def apply_filters(flights: list[dict], route: Any, *, enforce_price: bool = True) -> list[dict]:
    results = []
    airline_codes = _split_codes(route.airline_codes)
    origin_airports = _split_codes(route.origin_airports)
    destination_airports = _split_codes(route.destination_airports)

    for f in flights:
        # Price filter
        if enforce_price and f["price"] > route.max_price:
            continue

        # Direct only
        if route.direct_only and f["transfers"] != 0:
            continue

        # Airline filter
        if airline_codes and f["airline"].upper() not in airline_codes:
            continue

        # Origin airport filter
        if origin_airports and f["origin_airport"].upper() not in origin_airports:
            continue

        # Destination airport filter
        if destination_airports and f["destination_airport"].upper() not in destination_airports:
            continue

        # Departure time range
        if not _time_in_range(f["departure_at"], route.departure_time_from, route.departure_time_to):
            continue

        # Arrival time range (estimated)
        if not _time_in_range(f["estimated_arrival_at"], route.arrival_time_from, route.arrival_time_to):
            continue

        results.append(f)

    return results
