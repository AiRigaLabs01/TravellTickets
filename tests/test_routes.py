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
