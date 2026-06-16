import json
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.config import DEBUG_MONITORING_MESSAGES, TELEGRAM_CHAT_ID
from app.database import SessionLocal
from app.flight_filters import apply_filters
from app.models import Notification, PriceCheck, TrackedRoute
from app.telegram_notifier import (
    build_debug_monitoring_text,
    build_notification_text,
    send_telegram_notification,
)
from app.travelpayouts_client import TravelpayoutsError, search_prices
from app.yandex_links import build_yandex_travel_url

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _should_notify(route: TrackedRoute, flight: dict, db: Session) -> bool:
    price = flight["price"]
    flight_number = flight.get("flight_number", "")
    airline = flight.get("airline", "")

    existing = (
        db.query(Notification)
        .join(PriceCheck)
        .filter(
            Notification.tracked_route_id == route.id,
            PriceCheck.flight_number == flight_number,
            PriceCheck.airline == airline,
            PriceCheck.price == price,
        )
        .first()
    )
    if existing:
        return False

    if price <= route.max_price:
        return True
    if route.last_best_price is not None and price < route.last_best_price:
        return True
    return False


async def _send_debug_message(route: TrackedRoute, flights_count: int, filtered_count: int, best_flight: dict | None, error: str | None = None):
    if not DEBUG_MONITORING_MESSAGES:
        return
    chat_id = route.telegram_chat_id or TELEGRAM_CHAT_ID
    if not chat_id:
        return
    text = build_debug_monitoring_text(route, flights_count, filtered_count, best_flight, error)
    await send_telegram_notification(chat_id, text)


async def check_route(route_id: int):
    db: Session = SessionLocal()
    try:
        route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
        if not route or not route.is_active:
            return

        logger.info(f"Checking route #{route_id}: {route.origin} → {route.destination}")

        try:
            flights = await search_prices(route)
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

        filtered = apply_filters(flights, route)
        logger.info(f"Route #{route_id}: {len(flights)} flights found, {len(filtered)} after filters")

        best_flight = min(filtered, key=lambda f: f.get("price", 10**12)) if filtered else None

        for flight in filtered:
            yandex_url = build_yandex_travel_url(
                route.origin, route.destination, route.departure_date
            )
            flight["yandex_travel_url"] = yandex_url

            price_check = PriceCheck(
                tracked_route_id=route.id,
                checked_at=datetime.utcnow(),
                price=flight["price"],
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
            db.add(price_check)
            db.flush()

            if _should_notify(route, flight, db):
                chat_id = route.telegram_chat_id or TELEGRAM_CHAT_ID
                if chat_id:
                    text = build_notification_text(route, flight)
                    sent = await send_telegram_notification(chat_id, text)
                    if sent:
                        notif = Notification(
                            tracked_route_id=route.id,
                            price_check_id=price_check.id,
                            channel="telegram",
                            message=text,
                        )
                        db.add(notif)

            if route.last_best_price is None or flight["price"] < route.last_best_price:
                route.last_best_price = flight["price"]

        db.commit()
        await _send_debug_message(route, len(flights), len(filtered), best_flight)

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
    scheduler.add_job(
        check_route,
        trigger=IntervalTrigger(minutes=route.interval_minutes),
        id=job_id,
        args=[route.id],
        replace_existing=True,
        max_instances=1,
    )
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
