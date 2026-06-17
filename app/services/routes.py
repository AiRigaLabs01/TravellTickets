from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.auth import find_telegram_chat_id, normalize_telegram_username
from app.city_codes import city_label
from app.date_utils import format_route_date, parse_route_date
from app.models import Notification, PriceCheck, TrackedRoute, WebUser
from app.schemas import RouteFormData
from app.services.locations import resolve_route_location


@dataclass(frozen=True)
class RouteValidationResult:
    origin: str | None
    destination: str | None
    origin_airport: str | None
    destination_airport: str | None
    departure_date: str | None
    return_date: str | None
    errors: list[str]


def passenger_count(value: int | None, default: int = 0, min_value: int = 0, max_value: int = 9) -> int:
    try:
        return max(min(int(value if value is not None else default), max_value), min_value)
    except (TypeError, ValueError):
        return default


def reset_route_results(db: Session, route: TrackedRoute) -> None:
    db.query(Notification).filter(Notification.tracked_route_id == route.id).delete()
    db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route.id).delete()
    route.last_best_price = None
    route.last_checked_at = None
    route.last_error = None
    route.no_change_checks_count = 0


def delete_route(db: Session, route: TrackedRoute) -> None:
    from app.scheduler import unschedule_route

    route_id = route.id
    route.is_active = False
    db.commit()
    unschedule_route(route_id)
    db.query(Notification).filter(Notification.tracked_route_id == route_id).delete(synchronize_session=False)
    db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).delete(synchronize_session=False)
    db.delete(route)
    db.commit()


def resolve_route_notification(
    db: Session,
    user: WebUser | None,
    mode: str,
    username: str | None,
    errors: list[str],
) -> tuple[str, str | None, str | None]:
    notification_mode = "all" if mode == "all" else "telegram"
    notification_username = normalize_telegram_username(username)
    chat_id = None
    if notification_mode == "all":
        return notification_mode, None, None
    if not notification_username and user:
        notification_username = normalize_telegram_username(user.telegram_username)
        chat_id = user.telegram_chat_id
    if not notification_username:
        errors.append("Укажите Telegram username для уведомлений или выберите отправку всем")
        return notification_mode, None, None
    chat_id = chat_id or find_telegram_chat_id(db, notification_username)
    if not chat_id:
        known = db.query(WebUser).filter(WebUser.telegram_username == notification_username, WebUser.telegram_chat_id.isnot(None)).first()
        chat_id = known.telegram_chat_id if known else None
    return notification_mode, notification_username, chat_id


def validate_route_form(data: RouteFormData) -> RouteValidationResult:
    origin_location = resolve_route_location(data.origin)
    destination_location = resolve_route_location(data.destination)
    origin = origin_location.code if origin_location else None
    destination = destination_location.code if destination_location else None
    departure = parse_route_date(data.departure_date)
    return_date = parse_route_date(data.return_date) if data.trip_type == "roundtrip" and data.return_date else None
    errors: list[str] = []
    if not origin:
        errors.append("Не удалось определить город/аэропорт вылета")
    if not destination:
        errors.append("Не удалось определить город/аэропорт назначения")
    if not departure:
        errors.append("Неверная дата вылета")
    if data.trip_type == "roundtrip" and not return_date:
        errors.append("Для перелёта туда-обратно нужна дата возвращения")
    return RouteValidationResult(
        origin,
        destination,
        origin_location.airport_code if origin_location else None,
        destination_location.airport_code if destination_location else None,
        departure,
        return_date,
        errors,
    )


def _airport_filter(selected_airport: str | None, submitted_airports: str | None) -> str | None:
    selected = (selected_airport or "").upper().strip()
    if selected:
        return selected
    return (submitted_airports or "").upper().strip() or None


def apply_route_form(
    route: TrackedRoute,
    data: RouteFormData,
    validated: RouteValidationResult,
    notification_mode: str,
    notification_username: str | None,
    telegram_chat_id: str | None,
) -> bool:
    changed_core = (
        route.origin != validated.origin
        or route.destination != validated.destination
        or route.departure_date != validated.departure_date
    )
    route.origin = validated.origin or route.origin
    route.destination = validated.destination or route.destination
    route.departure_date = validated.departure_date or route.departure_date
    route.return_date = validated.return_date
    route.trip_type = "roundtrip" if data.trip_type == "roundtrip" else "oneway"
    route.adult_seats = passenger_count(data.adult_seats, 1, 1)
    route.children_seats = passenger_count(data.children_seats, 0)
    route.infant_seats = passenger_count(data.infant_seats, 0)
    route.baggage_required = data.baggage_required
    route.max_price = data.max_price
    route.interval_minutes = data.interval_minutes
    route.direct_only = data.direct_only
    route.airline_codes = (data.airline_codes or "").upper().strip() or None
    route.origin_airports = _airport_filter(validated.origin_airport, data.origin_airports)
    route.destination_airports = _airport_filter(validated.destination_airport, data.destination_airports)
    route.departure_time_from = data.departure_time_from or None
    route.departure_time_to = data.departure_time_to or None
    route.arrival_time_from = data.arrival_time_from or None
    route.arrival_time_to = data.arrival_time_to or None
    route.return_departure_time_from = data.return_departure_time_from or None
    route.return_departure_time_to = data.return_departure_time_to or None
    route.return_arrival_time_from = data.return_arrival_time_from or None
    route.return_arrival_time_to = data.return_arrival_time_to or None
    route.notification_mode = notification_mode
    route.notification_username = notification_username
    route.telegram_chat_id = telegram_chat_id
    route.creator_username = notification_username
    route.title = f"{city_label(route.origin)} → {city_label(route.destination)} {format_route_date(route.departure_date)}"
    return changed_core
