import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.city_codes import airline_label, airport_label, city_label, resolve_iata
from app.config import TELEGRAM_BOT_TOKEN
from app.database import SessionLocal, get_db, init_db
from app.locations import search_locations
from app.models import Notification, PriceCheck, TrackedRoute
from app.scheduler import check_route, load_all_routes, schedule_route, scheduler, unschedule_route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    load_all_routes()
    if TELEGRAM_BOT_TOKEN:
        try:
            from app.telegram_bot import create_bot
            import asyncio
            b, d = create_bot()
            app.state.bot = b
            app.state.dp = d
            asyncio.create_task(d.start_polling(b, handle_signals=False))
            logger.info("Telegram bot polling started")
        except Exception as e:
            logger.warning(f"Telegram bot could not start: {e}")
    yield
    scheduler.shutdown(wait=False)
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
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return v.strftime("%d.%m.%Y %H:%M")


def _fmt_time(v):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return v.strftime("%H:%M")


_jinja_env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
_jinja_env.filters["fmt_price"] = _fmt_price
_jinja_env.filters["fmt_dt"] = _fmt_dt
_jinja_env.filters["fmt_time"] = _fmt_time
_jinja_env.globals["airline_label"] = airline_label
_jinja_env.globals["airport_label"] = airport_label
_jinja_env.globals["city_label"] = city_label

app = FastAPI(title="TravellTickets", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(env=_jinja_env)


def _tr(request: Request, name: str, context: dict | None = None):
    return templates.TemplateResponse(request, name, context or {})


def _enrich_route(route: TrackedRoute) -> TrackedRoute:
    route.origin_city = city_label(route.origin)
    route.dest_city = city_label(route.destination)
    return route


def _reset_route_results(db: Session, route: TrackedRoute):
    db.query(Notification).filter(Notification.tracked_route_id == route.id).delete()
    db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route.id).delete()
    route.last_best_price = None
    route.last_checked_at = None
    route.last_error = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    routes = db.query(TrackedRoute).order_by(TrackedRoute.created_at.desc()).all()
    for r in routes:
        _enrich_route(r)
    last_checks: dict[int, PriceCheck] = {}
    for r in routes:
        last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == r.id).order_by(PriceCheck.checked_at.desc()).first()
        if last:
            last_checks[r.id] = last
    return _tr(request, "index.html", {"routes": routes, "last_checks": last_checks})


@app.get("/route/new", response_class=HTMLResponse)
async def route_new_form(request: Request):
    return _tr(request, "route_form.html", {"route": None, "errors": [], "origin_display": "", "dest_display": "", "today": date.today().isoformat()})


@app.post("/route/new")
async def route_new_submit(
    request: Request,
    title: Optional[str] = Form(None),
    origin: str = Form(...),
    destination: str = Form(...),
    origin_input: Optional[str] = Form(None),
    destination_input: Optional[str] = Form(None),
    departure_date: str = Form(...),
    max_price: float = Form(...),
    interval_minutes: int = Form(10),
    direct_only: bool = Form(False),
    airline_codes: Optional[str] = Form(None),
    origin_airports: Optional[str] = Form(None),
    destination_airports: Optional[str] = Form(None),
    departure_time_from: Optional[str] = Form(None),
    departure_time_to: Optional[str] = Form(None),
    arrival_time_from: Optional[str] = Form(None),
    arrival_time_to: Optional[str] = Form(None),
    telegram_chat_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    origin_code = resolve_iata(origin) if origin else ""
    dest_code = resolve_iata(destination) if destination else ""
    errors = []
    if not origin_code or len(origin_code) != 3:
        errors.append(f"Не удалось определить аэропорт вылета: «{origin_input or origin}». Введите название города или IATA-код (3 буквы).")
    if not dest_code or len(dest_code) != 3:
        errors.append(f"Не удалось определить аэропорт назначения: «{destination_input or destination}». Введите название города или IATA-код.")
    if max_price <= 0:
        errors.append("Максимальная цена должна быть больше нуля.")
    if interval_minutes not in (5, 10):
        interval_minutes = 10
    if errors:
        return _tr(request, "route_form.html", {"route": None, "errors": errors, "origin_display": origin_input or origin, "dest_display": destination_input or destination, "today": date.today().isoformat()})

    from app.config import TELEGRAM_CHAT_ID
    auto_title = title or f"{city_label(origin_code)} → {city_label(dest_code)} {departure_date}"
    route = TrackedRoute(
        title=auto_title,
        origin=origin_code,
        destination=dest_code,
        departure_date=departure_date,
        max_price=max_price,
        interval_minutes=interval_minutes,
        direct_only=direct_only,
        airline_codes=airline_codes or None,
        origin_airports=origin_airports or None,
        destination_airports=destination_airports or None,
        departure_time_from=departure_time_from or None,
        departure_time_to=departure_time_to or None,
        arrival_time_from=arrival_time_from or None,
        arrival_time_to=arrival_time_to or None,
        telegram_chat_id=telegram_chat_id or TELEGRAM_CHAT_ID or None,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    schedule_route(route)
    return RedirectResponse(url="/", status_code=303)


@app.get("/route/{route_id}", response_class=HTMLResponse)
async def route_detail(request: Request, route_id: int, db: Session = Depends(get_db)):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    _enrich_route(route)
    checks = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).limit(50).all()
    notifs = db.query(Notification).filter(Notification.tracked_route_id == route_id).order_by(Notification.sent_at.desc()).limit(20).all()
    return _tr(request, "route_detail.html", {"route": route, "checks": checks, "notifications": notifs})


@app.get("/route/{route_id}/edit", response_class=HTMLResponse)
async def route_edit_form(request: Request, route_id: int, db: Session = Depends(get_db)):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    _enrich_route(route)
    return _tr(request, "route_form.html", {"route": route, "errors": [], "origin_display": city_label(route.origin), "dest_display": city_label(route.destination), "today": date.today().isoformat()})


@app.post("/route/{route_id}/edit")
async def route_edit_submit(
    request: Request,
    route_id: int,
    title: Optional[str] = Form(None),
    origin: str = Form(...),
    destination: str = Form(...),
    origin_input: Optional[str] = Form(None),
    destination_input: Optional[str] = Form(None),
    departure_date: str = Form(...),
    max_price: float = Form(...),
    interval_minutes: int = Form(10),
    direct_only: bool = Form(False),
    airline_codes: Optional[str] = Form(None),
    origin_airports: Optional[str] = Form(None),
    destination_airports: Optional[str] = Form(None),
    departure_time_from: Optional[str] = Form(None),
    departure_time_to: Optional[str] = Form(None),
    arrival_time_from: Optional[str] = Form(None),
    arrival_time_to: Optional[str] = Form(None),
    telegram_chat_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")

    origin_code = resolve_iata(origin) if origin else ""
    dest_code = resolve_iata(destination) if destination else ""
    errors = []
    if not origin_code or len(origin_code) != 3:
        errors.append(f"Не удалось определить аэропорт вылета: «{origin_input or origin}».")
    if not dest_code or len(dest_code) != 3:
        errors.append(f"Не удалось определить аэропорт назначения: «{destination_input or destination}».")
    if max_price <= 0:
        errors.append("Максимальная цена должна быть больше нуля.")
    if errors:
        _enrich_route(route)
        return _tr(request, "route_form.html", {"route": route, "errors": errors, "origin_display": origin_input or origin, "dest_display": destination_input or destination, "today": date.today().isoformat()})

    route_changed = (route.origin != origin_code or route.destination != dest_code or route.departure_date != departure_date)
    if route_changed:
        _reset_route_results(db, route)

    route.origin = origin_code
    route.destination = dest_code
    route.departure_date = departure_date
    route.title = title or f"{city_label(origin_code)} → {city_label(dest_code)} {departure_date}"
    route.max_price = max_price
    route.interval_minutes = interval_minutes if interval_minutes in (5, 10) else 10
    route.direct_only = direct_only
    route.airline_codes = airline_codes or None
    route.origin_airports = origin_airports or None
    route.destination_airports = destination_airports or None
    route.departure_time_from = departure_time_from or None
    route.departure_time_to = departure_time_to or None
    route.arrival_time_from = arrival_time_from or None
    route.arrival_time_to = arrival_time_to or None
    if telegram_chat_id:
        route.telegram_chat_id = telegram_chat_id
    db.commit()
    if route.is_active:
        schedule_route(route)
    return RedirectResponse(url=f"/route/{route_id}", status_code=303)


@app.post("/route/{route_id}/check")
async def route_check_now(route_id: int, db: Session = Depends(get_db)):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    await check_route(route_id)
    return RedirectResponse(url=f"/route/{route_id}", status_code=303)


@app.post("/route/{route_id}/toggle")
async def route_toggle(route_id: int, db: Session = Depends(get_db)):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    route.is_active = not route.is_active
    db.commit()
    if route.is_active:
        schedule_route(route)
    else:
        unschedule_route(route_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/route/{route_id}/delete")
async def route_delete(route_id: int, db: Session = Depends(get_db)):
    route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    unschedule_route(route_id)
    db.delete(route)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/locations/search")
async def api_location_search(q: str = ""):
    return search_locations(q)


@app.get("/api/routes")
async def api_routes(db: Session = Depends(get_db)):
    routes = db.query(TrackedRoute).all()
    return [{"id": r.id, "title": r.title, "origin": r.origin, "destination": r.destination, "departure_date": r.departure_date, "max_price": r.max_price, "is_active": r.is_active, "last_best_price": r.last_best_price, "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None, "last_error": r.last_error} for r in routes]


@app.get("/api/routes/{route_id}/checks")
async def api_checks(route_id: int, db: Session = Depends(get_db)):
    checks = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).limit(100).all()
    return [{"id": c.id, "checked_at": c.checked_at.isoformat() if c.checked_at else None, "price": c.price, "airline": c.airline, "flight_number": c.flight_number, "gate": c.gate, "origin_airport": c.origin_airport, "destination_airport": c.destination_airport, "departure_at": c.departure_at.isoformat() if c.departure_at else None, "estimated_arrival_at": c.estimated_arrival_at.isoformat() if c.estimated_arrival_at else None, "transfers": c.transfers, "aviasales_url": c.aviasales_url, "yandex_travel_url": c.yandex_travel_url} for c in checks]
