"""Seed or verify the disposable PostgreSQL backup/restore CI rehearsal."""

import argparse
import os
from urllib.parse import urlsplit


def _require_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    parsed = urlsplit(database_url)
    if (
        os.environ.get("POSTGRES_REHEARSAL") != "1"
        or parsed.scheme not in ("postgres", "postgresql")
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username != "travelltickets_ci"
        or parsed.path not in ("/travelltickets_ci", "/travelltickets_restore_ci")
    ):
        raise SystemExit("Refusing to run outside the disposable CI PostgreSQL databases")


def seed() -> None:
    from app.database import SessionLocal, init_db
    from app.models import Notification, PriceCheck, TrackedRoute, WebUser

    init_db()
    init_db()
    with SessionLocal() as db:
        if db.query(WebUser).count() or db.query(TrackedRoute).count():
            raise SystemExit("Refusing to seed a non-empty rehearsal database")
        owner = WebUser(
            username="restore-owner",
            password_hash="synthetic-hash",
            display_name="Restore Owner",
            telegram_username="restore_owner",
            telegram_chat_id="900001",
            is_admin=False,
            is_active=True,
        )
        db.add(owner)
        db.flush()
        route = TrackedRoute(
            origin="MOW",
            destination="UFA",
            departure_date="2030-01-15",
            max_price=8123,
            telegram_chat_id="900001",
            web_user_id=owner.id,
            creator_source="telegram",
            creator_username="restore_owner",
            notification_username="restore_owner",
            last_best_price=7345,
        )
        db.add(route)
        db.flush()
        check = PriceCheck(
            tracked_route_id=route.id,
            price=7345,
            matches_filters=True,
            airline="CI",
            flight_number="RESTORE-1",
            origin="MOW",
            destination="UFA",
            aviasales_url="https://example.invalid/aviasales",
            yandex_travel_url="https://example.invalid/yandex",
        )
        db.add(check)
        db.flush()
        db.add(Notification(
            tracked_route_id=route.id,
            price_check_id=check.id,
            channel="telegram",
            message="synthetic restore notification",
        ))
        db.commit()
    print("Seeded disposable PostgreSQL rehearsal database.")


def verify() -> None:
    from app.database import SessionLocal, init_db
    from app.models import Notification, PriceCheck, TrackedRoute, WebUser

    # A restored release database must tolerate repeated application startup.
    init_db()
    init_db()
    with SessionLocal() as db:
        owner = db.query(WebUser).filter_by(username="restore-owner").one()
        route = db.query(TrackedRoute).filter_by(web_user_id=owner.id).one()
        check = db.query(PriceCheck).filter_by(tracked_route_id=route.id).one()
        notification = db.query(Notification).filter_by(price_check_id=check.id).one()
        assert owner.telegram_chat_id == "900001"
        assert route.origin == "MOW" and route.destination == "UFA"
        assert route.last_best_price == 7345
        assert check.flight_number == "RESTORE-1" and check.matches_filters is True
        assert notification.message == "synthetic restore notification"
        assert check.route.id == route.id
        assert notification.route.id == route.id

        # Restored sequences must continue without collisions.
        new_route = TrackedRoute(
            origin="LED", destination="AER", departure_date="2030-02-01",
            max_price=9000, web_user_id=owner.id,
        )
        db.add(new_route)
        db.commit()
        assert new_route.id > route.id
    print("Verified restored data, relationships, startup idempotency and sequences.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "verify"))
    args = parser.parse_args()
    _require_disposable_database()
    seed() if args.command == "seed" else verify()
