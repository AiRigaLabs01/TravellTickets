from app.database import SessionLocal, init_db
from app.models import Notification, PriceCheck, TrackedRoute
from app.services.routes import delete_route


def test_delete_route_removes_route_results(monkeypatch) -> None:
    import app.scheduler as scheduler

    init_db()
    removed: list[int] = []
    monkeypatch.setattr(scheduler, "unschedule_route", lambda route_id: removed.append(route_id))
    db = SessionLocal()
    try:
        route = TrackedRoute(origin="SVX", destination="MOW", departure_date="2026-06-20", max_price=4500)
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id
        check = PriceCheck(tracked_route_id=route_id, price=5471)
        db.add(check)
        db.commit()
        db.refresh(check)
        db.add(Notification(tracked_route_id=route_id, price_check_id=check.id, channel="telegram", message="test"))
        db.commit()

        delete_route(db, route)

        assert removed == [route_id]
        assert db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first() is None
        assert db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).count() == 0
        assert db.query(Notification).filter(Notification.tracked_route_id == route_id).count() == 0
    finally:
        db.close()


def test_check_route_exits_if_route_is_disabled_during_check(monkeypatch) -> None:
    import asyncio
    import app.scheduler as scheduler

    init_db()
    db = SessionLocal()
    try:
        route = TrackedRoute(origin="SVX", destination="MOW", departure_date="2026-06-20", max_price=4500)
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id
    finally:
        db.close()

    async def disable_during_check(route: TrackedRoute, db) -> tuple[int, int, dict | None, bool]:
        route.is_active = False
        db.add(PriceCheck(tracked_route_id=route.id, price=5471))
        db.flush()
        return 1, 1, {"price": 5471}, False

    monkeypatch.setattr(scheduler, "_check_oneway", disable_during_check)

    asyncio.run(scheduler.check_route(route_id))

    db = SessionLocal()
    try:
        route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
        assert route is not None
        assert route.last_checked_at is None
        assert db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).count() == 0
    finally:
        db.close()


def test_midnight_departure_window_includes_next_morning() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.flight_filters import apply_filters

    route = SimpleNamespace(
        max_price=10000,
        direct_only=False,
        airline_codes=None,
        origin_airports=None,
        destination_airports=None,
        departure_date="2026-06-20",
        departure_time_from="23:00",
        departure_time_to="05:00",
        arrival_time_from=None,
        arrival_time_to=None,
    )
    flights = [
        {"price": 5000, "transfers": 0, "airline": "U6", "origin_airport": "SVX", "destination_airport": "DME", "departure_at": datetime(2026, 6, 20, 23, 30), "estimated_arrival_at": None},
        {"price": 5000, "transfers": 0, "airline": "U6", "origin_airport": "SVX", "destination_airport": "DME", "departure_at": datetime(2026, 6, 21, 4, 30), "estimated_arrival_at": None},
        {"price": 5000, "transfers": 0, "airline": "U6", "origin_airport": "SVX", "destination_airport": "DME", "departure_at": datetime(2026, 6, 21, 6, 0), "estimated_arrival_at": None},
        {"price": 5000, "transfers": 0, "airline": "U6", "origin_airport": "SVX", "destination_airport": "DME", "departure_at": datetime(2026, 6, 20, 10, 0), "estimated_arrival_at": None},
    ]

    result = apply_filters(flights, route, enforce_price=True)

    assert [flight["departure_at"].hour for flight in result] == [23, 4]


def test_search_prices_queries_next_day_for_midnight_window(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    import app.travelpayouts_client as client

    calls: list[str] = []

    async def fake_search(origin: str, destination: str, departure_date: str, direct_only: bool = False) -> list[dict]:
        calls.append(departure_date)
        return [{"airline": "U6", "flight_number": departure_date, "departure_at_raw": departure_date, "origin_airport": origin}]

    route = SimpleNamespace(
        origin="SVX",
        destination="MOW",
        departure_date="2026-06-20",
        direct_only=False,
        departure_time_from="23:00",
        departure_time_to="05:00",
    )
    monkeypatch.setattr(client, "search_prices_for_leg", fake_search)

    flights = asyncio.run(client.search_prices(route))

    assert calls == ["2026-06-20", "2026-06-21"]
    assert [flight["flight_number"] for flight in flights] == ["2026-06-20", "2026-06-21"]
