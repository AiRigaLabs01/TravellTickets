import json
import logging
from datetime import datetime
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.config import DEBUG_MONITORING_MESSAGES, TELEGRAM_CHAT_ID
from app.database import SessionLocal
from app.flight_filters import apply_filters
from app.models import Notification, PriceCheck, TrackedRoute
from app.telegram_notifier import (
    build_debug_monitoring_text,
    build_no_changes_text,
    build_notification_text,
    send_telegram_notification,
)
from app.travelpayouts_client import TravelpayoutsError, search_prices, search_prices_for_leg
from app.yandex_links import build_yandex_travel_url_for_route

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
NO_CHANGE_NOTIFY_EVERY = 3


def _notification_chat_id(route: TrackedRoute) -> str | None:
    if route.telegram_chat_id:
        return route.telegram_chat_id
    if getattr(route, "web_user_id", None):
        return None
    return TELEGRAM_CHAT_ID


def _should_notify(route: TrackedRoute, flight: dict, db: Session) -> bool:
    price = flight["price"]
    flight_number = flight.get("flight_number", "")
    airline = flight.get("airline", "")
    existing = db.query(Notification).join(PriceCheck).filter(
        Notification.tracked_route_id == route.id,
        PriceCheck.flight_number == flight_number,
        PriceCheck.airline == airline,
        PriceCheck.price == price,
        PriceCheck.matches_filters == True,
    ).first()
    return existing is None and price <= route.max_price


def _make_price_check(route: TrackedRoute, flight: dict, yandex_url: str, matches_filters: bool) -> PriceCheck:
    return PriceCheck(
        tracked_route_id=route.id,
        checked_at=datetime.utcnow(),
        price=flight["price"],
        matches_filters=matches_filters,
        airline=flight.get("airline"),
        flight_number=flight.get("flight_number"),
        gate=flight.get("gate"),
        origin=flight.get("origin"),
        destination=flight.get("destination"),
        origin_airport=flight.get("origin_airport"),
        destination_airport=flight.get("destination_airport"),
        departure_at=flight.get("departure_at"),
        duration=flight.get("duration"),
        estimated_arrival_at=flight.get("estimated_arrival_at"),
        is_estimated_arrival=flight.get("is_estimated_arrival", True),
        transfers=flight.get("transfers", 0),
        link=flight.get("link"),
        aviasales_url=flight.get("aviasales_url"),
        yandex_travel_url=yandex_url,
        raw_json=json.dumps(flight.get("raw_json", {}), default=str),
    )


def _return_leg_route(route: TrackedRoute):
    return SimpleNamespace(
        origin=route.destination,
        destination=route.origin,
        departure_date=route.return_date,
        direct_only=route.direct_only,
        airline_codes=route.airline_codes,
        origin_airports=None,
        destination_airports=route.origin_airports,
        departure_time_from=route.return_departure_time_from,
        departure_time_to=route.return_departure_time_to,
        arrival_time_from=route.return_arrival_time_from,
        arrival_time_to=route.return_arrival_time_to,
        max_price=route.max_price,
    )


def _roundtrip_flight(outbound: dict, inbound: dict, yandex_url: str) -> dict:
    total_price = float(outbound.get("price", 0)) + float(inbound.get("price", 0))
    out_no = outbound.get("flight_number", "")
    in_no = inbound.get("flight_number", "")
    out_airline = outbound.get("airline", "")
    in_airline = inbound.get("airline", "")
    return {
        "price": total_price,
        "airline": out_airline if out_airline == in_airline else f"{out_airline}/{in_airline}",
        "flight_number": f"{out_no}/{in_no}",
        "gate": outbound.get("gate") or inbound.get("gate"),
        "origin": outbound.get("origin"),
        "destination": inbound.get("destination"),
        "origin_airport": outbound.get("origin_airport"),
        "destination_airport": inbound.get("destination_airport"),
        "departure_at": outbound.get("departure_at"),
        "duration": (outbound.get("duration") or 0) + (inbound.get("duration") or 0),
        "estimated_arrival_at": inbound.get("estimated_arrival_at"),
        "is_estimated_arrival": True,
        "transfers": (outbound.get("transfers") or 0) + (inbound.get("transfers") or 0),
        "link": outbound.get("link"),
        "aviasales_url": outbound.get("aviasales_url"),
        "yandex_travel_url": yandex_url,
        "return_flight": inbound,
        "raw_json": {"trip_type": "roundtrip", "outbound": outbound, "return": inbound},
    }


def _best_roundtrip(outbound: list[dict], inbound: list[dict], yandex_url: str) -> dict | None:
    if not outbound or not inbound:
        return None
    best = None
    for out in outbound:
        for ret in inbound:
            combo = _roundtrip_flight(out, ret, yandex_url)
            if best is None or combo["price"] < best["price"]:
                best = combo
    return best


async def _send_debug_message(route: TrackedRoute, flights_count: int, filtered_count: int, best_flight: dict | None, error: str | None = None):
    if not DEBUG_MONITORING_MESSAGES:
        return
    chat_id = _notification_chat_id(route)
    if not chat_id:
        return
    text = build_debug_monitoring_text(route, flights_count, filtered_count, best_flight, error)
    await send_telegram_notification(chat_id, text)


async def _send_no_changes_message(route: TrackedRoute, flights_count: int, filtered_count: int, best_flight: dict | None):
    chat_id = _notification_chat_id(route)
    if not chat_id:
        return False
    text = build_no_changes_text(route, flights_count, filtered_count, best_flight)
    return await send_telegram_notification(chat_id, text)


async def _check_roundtrip(route: TrackedRoute, db: Session):
    yandex_url = build_yandex_travel_url_for_route(route)
    return_route = _return_leg_route(route)
    outbound_flights = await search_prices(route)
    return_flights = await search_prices_for_leg(route.destination, route.origin, route.return_date, route.direct_only)
    outbound = apply_filters(outbound_flights, route, enforce_price=False)
    inbound = apply_filters(return_flights, return_route, enforce_price=False)
    best = _best_roundtrip(outbound, inbound, yandex_url)
    filtered_count = 1 if best and best["price"] <= route.max_price else 0
    if best and best["price"] > route.max_price:
        best["above_limit"] = True
        best["limit_price"] = route.max_price
    total_api_count = len(outbound_flights) + len(return_flights)
    notification_sent = False

    if best:
        matches = best["price"] <= route.max_price
        price_check = _make_price_check(route, best, yandex_url, matches)
        db.add(price_check)
        db.flush()
        if matches and _should_notify(route, best, db):
            chat_id = _notification_chat_id(route)
            if chat_id:
                text = build_notification_text(route, best)
                sent = await send_telegram_notification(chat_id, text)
                if sent:
                    notification_sent = True
                    route.no_change_checks_count = 0
                    db.add(Notification(tracked_route_id=route.id, price_check_id=price_check.id, channel="telegram", message=text))
        if matches and (route.last_best_price is None or best["price"] < route.last_best_price):
            route.last_best_price = best["price"]

    return total_api_count, filtered_count, best, notification_sent


async def _check_oneway(route: TrackedRoute, db: Session):
    flights = await search_prices(route)
    filtered = apply_filters(flights, route, enforce_price=True)
    comparable = apply_filters(flights, route, enforce_price=False)
    best_flight = min(filtered, key=lambda f: f.get("price", 10**12)) if filtered else None
    best_any_flight = min(comparable, key=lambda f: f.get("price", 10**12)) if comparable else None
    status_flight = best_flight or best_any_flight
    if status_flight and not best_flight and status_flight.get("price", 0) > route.max_price:
        status_flight["above_limit"] = True
        status_flight["limit_price"] = route.max_price

    yandex_url = build_yandex_travel_url_for_route(route)
    notification_sent = False

    for flight in sorted(filtered, key=lambda f: f.get("price", 10**12)):
        flight["yandex_travel_url"] = yandex_url
        price_check = _make_price_check(route, flight, yandex_url, True)
        db.add(price_check)
        db.flush()
        if _should_notify(route, flight, db):
            chat_id = _notification_chat_id(route)
            if chat_id:
                text = build_notification_text(route, flight)
                sent = await send_telegram_notification(chat_id, text)
                if sent:
                    notification_sent = True
                    route.no_change_checks_count = 0
                    db.add(Notification(tracked_route_id=route.id, price_check_id=price_check.id, channel="telegram", message=text))
        if route.last_best_price is None or flight["price"] < route.last_best_price:
            route.last_best_price = flight["price"]

    if not filtered and best_any_flight:
        best_any_flight["yandex_travel_url"] = yandex_url
        db.add(_make_price_check(route, best_any_flight, yandex_url, False))

    return len(flights), len(filtered), status_flight, notification_sent


async def check_route(route_id: int):
    db: Session = SessionLocal()
    try:
        route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
        if not route or not route.is_active:
            return
        logger.info(f"Checking route #{route_id}: {route.origin} → {route.destination}")
        try:
            if route.trip_type == "roundtrip" and route.return_date:
                flights_count, filtered_count, status_flight, notification_sent = await _check_roundtrip(route, db)
            else:
                flights_count, filtered_count, status_flight, notification_sent = await _check_oneway(route, db)
        except TravelpayoutsError as e:
            error_msg = str(e)
            logger.error(f"Route #{route_id} API error: {error_msg}")
            route.last_error = error_msg
            route.last_checked_at = datetime.utcnow()
            db.commit()
            await _send_debug_message(route, 0, 0, None, error_msg)
            return

        route.last_error = None
        route.last_checked_at = datetime.utcnow()
        logger.info(f"Route #{route_id}: {flights_count} flights found, {filtered_count} after filters")

        if not notification_sent:
            route.no_change_checks_count = (route.no_change_checks_count or 0) + 1
        db.commit()

        if not notification_sent and (route.no_change_checks_count or 0) >= NO_CHANGE_NOTIFY_EVERY:
            sent = await _send_no_changes_message(route, flights_count, filtered_count, status_flight)
            if sent:
                route.no_change_checks_count = 0
                db.commit()
        await _send_debug_message(route, flights_count, filtered_count, status_flight)
    except Exception as e:
        logger.exception(f"Unexpected error checking route #{route_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def schedule_route(route: TrackedRoute):
    job_id = f"route_{route.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(check_route, trigger=IntervalTrigger(minutes=route.interval_minutes), id=job_id, args=[route.id], replace_existing=True, max_instances=1)
    logger.info(f"Scheduled route #{route.id} every {route.interval_minutes} minutes")


def unschedule_route(route_id: int):
    job_id = f"route_{route_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Unscheduled route #{route_id}")


def load_all_routes():
    db: Session = SessionLocal()
    try:
        routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
        for route in routes:
            schedule_route(route)
        logger.info(f"Loaded {len(routes)} active routes into scheduler")
    finally:
        db.close()
