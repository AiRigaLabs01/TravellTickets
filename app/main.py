import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.city_codes import airline_label, airport_label, city_label, resolve_iata
from app.config import TELEGRAM_BOT_TOKEN
from app.database import get_db, init_db
from app.date_utils import format_msk_datetime, format_msk_time, format_route_date, parse_route_date
from app.locations import search_locations
from app.models import Notification, PriceCheck, TrackedRoute, WebUser
from app.auth import find_telegram_chat_id, get_current_web_user, normalize_telegram_username, verify_telegram_access_token
from app.repositories import RouteRepository
from app.scheduler import check_route, load_all_routes, schedule_route, scheduler, unschedule_route
from app.services.routes import passenger_count, reset_route_results
from app.web_admin import install_web_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _run_telegram_polling(app: FastAPI):
    from app.telegram_bot import create_bot
    import asyncio

    while True:
        b, d = create_bot()
        app.state.bot = b
        app.state.dp = d
        try:
            logger.info("Telegram bot polling started")
            await d.start_polling(b, handle_signals=False)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Telegram bot polling stopped, restarting in 15s: {e}")
            try:
                await b.session.close()
            except Exception:
                pass
            await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    load_all_routes()
    if TELEGRAM_BOT_TOKEN:
        try:
            import asyncio
            app.state.telegram_task = asyncio.create_task(_run_telegram_polling(app))
        except Exception as e:
            logger.warning(f"Telegram bot could not start: {e}")
    yield
    scheduler.shutdown(wait=False)
    if hasattr(app.state, "telegram_task"):
        app.state.telegram_task.cancel()
    if hasattr(app.state, "bot"):
        try:
            await app.state.bot.session.close()
        except Exception:
            pass


def _fmt_price(v):
    if v is None:
        return "—"
    return f"{int(v):,}".replace(",", "\u00a0") + "\u00a0₽"


def _fmt_dt(v):
    return format_msk_datetime(v)


def _fmt_time(v):
    return format_msk_time(v)


def _creator_label(route):
    source = getattr(route, "creator_source", None) or "web"
    if source == "telegram":
        return getattr(route, "creator_display_name", None) or getattr(route, "creator_username", None) or getattr(route, "creator_telegram_user_id", None) or getattr(route, "telegram_chat_id", None) or "Telegram"
    return getattr(route, "creator_display_name", None) or "Веб-интерфейс"


_jinja_env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
_jinja_env.filters["fmt_price"] = _fmt_price
_jinja_env.filters["fmt_dt"] = _fmt_dt
_jinja_env.filters["fmt_time"] = _fmt_time
_jinja_env.filters["fmt_route_date"] = format_route_date
_jinja_env.globals["airline_label"] = airline_label
_jinja_env.globals["airport_label"] = airport_label
_jinja_env.globals["city_label"] = city_label
_jinja_env.globals["creator_label"] = _creator_label

app = FastAPI(title="TravellTickets", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(env=_jinja_env)
install_web_admin(app)


def _tr(request: Request, name: str, context: dict | None = None):
    context = context or {}
    if request is not None and "current_user" not in context:
        context["current_user"] = getattr(request.state, "current_user", None)
    return templates.TemplateResponse(request, name, context)


def _enrich_route(route: TrackedRoute) -> TrackedRoute:
    route.origin_city = city_label(route.origin)
    route.dest_city = city_label(route.destination)
    return route


def _reset_route_results(db: Session, route: TrackedRoute):
    reset_route_results(db, route)


def _passenger_count(value: int | None, default: int = 0, min_value: int = 0, max_value: int = 9) -> int:
    return passenger_count(value, default, min_value, max_value)


def _routes_for_user(db: Session, user):
    return RouteRepository(db).query_for_web_user(user)


def _routes_for_telegram_payload(db: Session, payload: dict):
    return RouteRepository(db).query_for_telegram_payload(payload)


def _telegram_payload_or_403(token: str | None) -> dict:
    payload = verify_telegram_access_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Telegram link is expired or invalid")
    return payload


def _notification_label(route):
    mode = getattr(route, "notification_mode", None) or "telegram"
    if mode == "all":
        return "всем"
    username = getattr(route, "notification_username", None) or getattr(route, "creator_username", None)
    if username:
        return f"@{username}"
    return "не назначено"


_jinja_env.globals["notification_label"] = _notification_label


def _route_form_context(route=None, errors=None, origin_display="", dest_display=""):
    return {"route": route, "errors": errors or [], "origin_display": origin_display, "dest_display": dest_display, "today": date.today().isoformat()}


def _resolve_route_notification(db: Session, user, mode: str, username: str | None, errors: list[str]) -> tuple[str, str | None, str | None]:
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    request.state.current_user = user
    routes = _routes_for_user(db, user).order_by(TrackedRoute.created_at.desc()).all()
    for r in routes:
        _enrich_route(r)
    last_checks: dict[int, PriceCheck] = {}
    for r in routes:
        last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == r.id).order_by(PriceCheck.checked_at.desc()).first()
        if last:
            last_checks[r.id] = last
    return _tr(request, "index.html", {"routes": routes, "last_checks": last_checks})


@app.get("/public", response_class=HTMLResponse)
async def public_page(request: Request):
    return _tr(request, "public.html")


@app.get("/tg/monitorings", response_class=HTMLResponse)
async def telegram_monitorings(request: Request, token: str, db: Session = Depends(get_db)):
    payload = _telegram_payload_or_403(token)
    routes = _routes_for_telegram_payload(db, payload).order_by(TrackedRoute.created_at.desc()).all()
    for r in routes:
        _enrich_route(r)
    last_checks: dict[int, PriceCheck] = {}
    for r in routes:
        last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == r.id).order_by(PriceCheck.checked_at.desc()).first()
        if last:
            last_checks[r.id] = last
    return _tr(request, "tg_monitorings.html", {"routes": routes, "last_checks": last_checks, "token": token})


@app.get("/tg/route/{route_id}", response_class=HTMLResponse)
async def telegram_route_detail(request: Request, route_id: int, token: str, db: Session = Depends(get_db)):
    payload = _telegram_payload_or_403(token)
    token_route_id = payload.get("route_id")
    if token_route_id is not None and int(token_route_id) != route_id:
        raise HTTPException(status_code=404)
    route = _routes_for_telegram_payload(db, payload).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404)
    _enrich_route(route)
    checks = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).limit(50).all()
    return _tr(request, "tg_route_detail.html", {"route": route, "checks": checks, "token": token})


@app.get("/route/new", response_class=HTMLResponse)
async def route_new_form(request: Request):
    return _tr(request, "route_form.html", _route_form_context())


@app.post("/route/new")
async def route_create(
    request: Request,
    origin: str = Form(...),
    destination: str = Form(...),
    departure_date: str = Form(...),
    return_date: Optional[str] = Form(None),
    trip_type: str = Form("oneway"),
    adult_seats: int = Form(1),
    children_seats: int = Form(0),
    infant_seats: int = Form(0),
    baggage_required: Optional[str] = Form(None),
    max_price: float = Form(...),
    interval_minutes: int = Form(10),
    direct_only: Optional[str] = Form(None),
    airline_codes: Optional[str] = Form(None),
    origin_airports: Optional[str] = Form(None),
    destination_airports: Optional[str] = Form(None),
    departure_time_from: Optional[str] = Form(None),
    departure_time_to: Optional[str] = Form(None),
    arrival_time_from: Optional[str] = Form(None),
    arrival_time_to: Optional[str] = Form(None),
    return_departure_time_from: Optional[str] = Form(None),
    return_departure_time_to: Optional[str] = Form(None),
    return_arrival_time_from: Optional[str] = Form(None),
    return_arrival_time_to: Optional[str] = Form(None),
    notification_mode: str = Form("telegram"),
    notification_username: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    o, d = resolve_iata(origin), resolve_iata(destination)
    iso_date = parse_route_date(departure_date)
    return_iso = parse_route_date(return_date) if trip_type == "roundtrip" and return_date else None
    errors = []
    if len(o) != 3: errors.append("Не удалось определить город/аэропорт вылета")
    if len(d) != 3: errors.append("Не удалось определить город/аэропорт назначения")
    if not iso_date: errors.append("Неверная дата вылета")
    if trip_type == "roundtrip" and not return_iso: errors.append("Для перелёта туда-обратно нужна дата возвращения")
    user = get_current_web_user(request, db)
    notification_mode, notification_username, telegram_chat_id = _resolve_route_notification(db, user, notification_mode, notification_username, errors)
    if errors:
        return _tr(request, "route_form.html", _route_form_context(errors=errors, origin_display=origin, dest_display=destination))
    display_name = (user.display_name or user.username) if user else "Веб-интерфейс"
    route = TrackedRoute(
        origin=o,
        destination=d,
        departure_date=iso_date,
        return_date=return_iso,
        trip_type="roundtrip" if trip_type == "roundtrip" else "oneway",
        adult_seats=_passenger_count(adult_seats, 1, 1),
        children_seats=_passenger_count(children_seats, 0),
        infant_seats=_passenger_count(infant_seats, 0),
        baggage_required=bool(baggage_required),
        max_price=max_price,
        interval_minutes=interval_minutes,
        direct_only=bool(direct_only),
        airline_codes=(airline_codes or "").upper().strip() or None,
        origin_airports=(origin_airports or "").upper().strip() or None,
        destination_airports=(destination_airports or "").upper().strip() or None,
        departure_time_from=departure_time_from or None,
        departure_time_to=departure_time_to or None,
        arrival_time_from=arrival_time_from or None,
        arrival_time_to=arrival_time_to or None,
        return_departure_time_from=return_departure_time_from or None,
        return_departure_time_to=return_departure_time_to or None,
        return_arrival_time_from=return_arrival_time_from or None,
        return_arrival_time_to=return_arrival_time_to or None,
        title=f"{city_label(o)} → {city_label(d)} {format_route_date(iso_date)}",
        creator_source="web",
        telegram_chat_id=telegram_chat_id,
        notification_mode=notification_mode,
        notification_username=notification_username,
        web_user_id=user.id if user else None,
        creator_display_name=display_name,
        creator_username=notification_username,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    schedule_route(route)
    return RedirectResponse("/", status_code=303)


@app.get("/route/{route_id}/edit", response_class=HTMLResponse)
async def route_edit_form(request: Request, route_id: int, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    request.state.current_user = user
    route = _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404)
    return _tr(request, "route_form.html", _route_form_context(route=route, origin_display=city_label(route.origin), dest_display=city_label(route.destination)))


@app.post("/route/{route_id}/edit")
async def route_edit(
    request: Request,
    route_id: int,
    origin: str = Form(...),
    destination: str = Form(...),
    departure_date: str = Form(...),
    return_date: Optional[str] = Form(None),
    trip_type: str = Form("oneway"),
    adult_seats: int = Form(1),
    children_seats: int = Form(0),
    infant_seats: int = Form(0),
    baggage_required: Optional[str] = Form(None),
    max_price: float = Form(...),
    interval_minutes: int = Form(10),
    direct_only: Optional[str] = Form(None),
    airline_codes: Optional[str] = Form(None),
    origin_airports: Optional[str] = Form(None),
    destination_airports: Optional[str] = Form(None),
    departure_time_from: Optional[str] = Form(None),
    departure_time_to: Optional[str] = Form(None),
    arrival_time_from: Optional[str] = Form(None),
    arrival_time_to: Optional[str] = Form(None),
    return_departure_time_from: Optional[str] = Form(None),
    return_departure_time_to: Optional[str] = Form(None),
    return_arrival_time_from: Optional[str] = Form(None),
    return_arrival_time_to: Optional[str] = Form(None),
    notification_mode: str = Form("telegram"),
    notification_username: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_web_user(request, db)
    route = _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404)
    o, d = resolve_iata(origin), resolve_iata(destination)
    iso_date = parse_route_date(departure_date)
    return_iso = parse_route_date(return_date) if trip_type == "roundtrip" and return_date else None
    errors = []
    if len(o) != 3: errors.append("Не удалось определить город/аэропорт вылета")
    if len(d) != 3: errors.append("Не удалось определить город/аэропорт назначения")
    if not iso_date: errors.append("Неверная дата вылета")
    if trip_type == "roundtrip" and not return_iso: errors.append("Для перелёта туда-обратно нужна дата возвращения")
    notification_mode, notification_username, telegram_chat_id = _resolve_route_notification(db, user, notification_mode, notification_username, errors)
    if errors:
        return _tr(request, "route_form.html", _route_form_context(route=route, errors=errors, origin_display=origin, dest_display=destination))
    changed_core = (o != route.origin or d != route.destination or iso_date != route.departure_date)
    route.origin, route.destination, route.departure_date = o, d, iso_date
    route.return_date = return_iso
    route.trip_type = "roundtrip" if trip_type == "roundtrip" else "oneway"
    route.adult_seats = _passenger_count(adult_seats, 1, 1)
    route.children_seats = _passenger_count(children_seats, 0)
    route.infant_seats = _passenger_count(infant_seats, 0)
    route.baggage_required = bool(baggage_required)
    route.max_price = max_price
    route.interval_minutes = interval_minutes
    route.direct_only = bool(direct_only)
    route.airline_codes = (airline_codes or "").upper().strip() or None
    route.origin_airports = (origin_airports or "").upper().strip() or None
    route.destination_airports = (destination_airports or "").upper().strip() or None
    route.departure_time_from = departure_time_from or None
    route.departure_time_to = departure_time_to or None
    route.arrival_time_from = arrival_time_from or None
    route.arrival_time_to = arrival_time_to or None
    route.return_departure_time_from = return_departure_time_from or None
    route.return_departure_time_to = return_departure_time_to or None
    route.return_arrival_time_from = return_arrival_time_from or None
    route.return_arrival_time_to = return_arrival_time_to or None
    route.notification_mode = notification_mode
    route.notification_username = notification_username
    route.telegram_chat_id = telegram_chat_id
    route.creator_username = notification_username
    route.title = f"{city_label(o)} → {city_label(d)} {format_route_date(iso_date)}"
    if changed_core:
        _reset_route_results(db, route)
    db.commit()
    schedule_route(route)
    return RedirectResponse(f"/route/{route_id}", status_code=303)


@app.get("/route/{route_id}", response_class=HTMLResponse)
async def route_detail(request: Request, route_id: int, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    request.state.current_user = user
    route = _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404)
    _enrich_route(route)
    checks = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).limit(50).all()
    notifications = db.query(Notification).filter(Notification.tracked_route_id == route_id).order_by(Notification.sent_at.desc()).limit(20).all()
    return _tr(request, "route_detail.html", {"route": route, "checks": checks, "notifications": notifications})


@app.post("/route/{route_id}/check")
async def route_check(request: Request, route_id: int, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    if not _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first():
        raise HTTPException(status_code=404)
    await check_route(route_id)
    return RedirectResponse(f"/route/{route_id}", status_code=303)


@app.post("/route/{route_id}/toggle")
async def route_toggle(request: Request, route_id: int, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    route = _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404)
    route.is_active = not route.is_active
    db.commit()
    if route.is_active:
        schedule_route(route)
    else:
        unschedule_route(route.id)
    return RedirectResponse("/", status_code=303)


@app.post("/route/{route_id}/delete")
async def route_delete(request: Request, route_id: int, db: Session = Depends(get_db)):
    user = get_current_web_user(request, db)
    route = _routes_for_user(db, user).filter(TrackedRoute.id == route_id).first()
    if route:
        unschedule_route(route.id)
        db.delete(route)
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/api/v1/locations/search")
async def locations_search(q: str = ""):
    return search_locations(q)


@app.get("/api/locations/search")
async def locations_search_legacy(q: str = ""):
    return await locations_search(q)


@app.get("/api/v1/routes")
async def api_routes(db: Session = Depends(get_db)):
    routes = db.query(TrackedRoute).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "origin": r.origin,
            "destination": r.destination,
            "departure_date": r.departure_date,
            "return_date": r.return_date,
            "trip_type": r.trip_type,
            "adult_seats": r.adult_seats,
            "children_seats": r.children_seats,
            "infant_seats": r.infant_seats,
            "baggage_required": r.baggage_required,
            "max_price": r.max_price,
            "last_best_price": r.last_best_price,
            "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
            "is_active": r.is_active,
            "last_error": r.last_error,
        }
        for r in routes
    ]


@app.get("/api/routes")
async def api_routes_legacy(db: Session = Depends(get_db)):
    return await api_routes(db)
