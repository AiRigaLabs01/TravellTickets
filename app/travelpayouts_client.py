import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import AVIASALES_BASE_URL, AVIASALES_SITE_BASE, TRAVELPAYOUTS_TOKEN

logger = logging.getLogger(__name__)


class TravelpayoutsError(Exception):
    pass


class RateLimitError(TravelpayoutsError):
    pass


def _build_aviasales_url(link: str) -> str:
    if not link:
        return ""
    if link.startswith("http"):
        return link
    return AVIASALES_SITE_BASE + link


@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    stop=stop_after_attempt(4),
)
async def _fetch_prices(params: dict) -> dict:
    headers = {"X-Access-Token": TRAVELPAYOUTS_TOKEN}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(AVIASALES_BASE_URL, params=params, headers=headers)
        if resp.status_code == 429:
            logger.warning("Travelpayouts rate limit hit, retrying...")
            raise RateLimitError("429 Too Many Requests")
        if resp.status_code != 200:
            raise TravelpayoutsError(f"API returned {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if not data.get("success"):
            raise TravelpayoutsError(f"API success=false: {data}")
        return data


def _normalize_flight(item: dict) -> dict:
    departure_at_raw = item.get("departure_at", "")
    departure_dt = None
    estimated_arrival_dt = None

    try:
        departure_dt = datetime.fromisoformat(departure_at_raw)
    except (ValueError, TypeError):
        pass

    duration_minutes = item.get("duration", 0) or 0
    if departure_dt and duration_minutes:
        estimated_arrival_dt = departure_dt + timedelta(minutes=duration_minutes)

    link = item.get("link", "")

    return {
        "flight_number": str(item.get("flight_number", "")),
        "link": link,
        "aviasales_url": _build_aviasales_url(link),
        "origin": item.get("origin", ""),
        "destination": item.get("destination", ""),
        "origin_airport": item.get("origin_airport", ""),
        "destination_airport": item.get("destination_airport", ""),
        "departure_at": departure_dt,
        "departure_at_raw": departure_at_raw,
        "airline": item.get("airline", ""),
        "gate": item.get("gate", ""),
        "price": float(item.get("price", 0)),
        "transfers": int(item.get("transfers", 0)),
        "duration": duration_minutes,
        "estimated_arrival_at": estimated_arrival_dt,
        "is_estimated_arrival": True,
        "raw_json": item,
    }


async def search_prices_for_leg(origin: str, destination: str, departure_date: str, direct_only: bool = False) -> list[dict]:
    """Search one route leg via Travelpayouts Aviasales API."""
    if not TRAVELPAYOUTS_TOKEN:
        raise TravelpayoutsError("TRAVELPAYOUTS_TOKEN is not configured")

    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": departure_date,
        "currency": "rub",
        "market": "ru",
        "limit": 30,
        "sorting": "price",
    }
    if direct_only:
        params["direct"] = "true"

    data = await _fetch_prices(params)
    return [_normalize_flight(item) for item in data.get("data", [])]


def _time_total(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except (ValueError, TypeError):
        return None


def _departure_window_crosses_midnight(route: Any) -> bool:
    from_total = _time_total(getattr(route, "departure_time_from", None))
    to_total = _time_total(getattr(route, "departure_time_to", None))
    return from_total is not None and to_total is not None and from_total > to_total


async def search_prices(route: Any) -> list[dict]:
    """
    Search prices via Travelpayouts Aviasales API.
    Returns list of normalized flight dicts.
    """
    dates = [route.departure_date]
    if _departure_window_crosses_midnight(route):
        next_date = datetime.fromisoformat(route.departure_date).date() + timedelta(days=1)
        dates.append(next_date.isoformat())

    flights: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for departure_date in dates:
        for flight in await search_prices_for_leg(route.origin, route.destination, departure_date, route.direct_only):
            key = (
                flight.get("airline", ""),
                flight.get("flight_number", ""),
                flight.get("departure_at_raw", ""),
                flight.get("origin_airport", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            flights.append(flight)
    return flights
