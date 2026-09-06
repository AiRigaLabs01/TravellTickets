import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.auth as auth
import app.database as database
from app.models import TrackedRoute, WebUser


@pytest.fixture
def isolated_database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "test-hash")
    database.Base.metadata.create_all(engine)
    yield sessions
    engine.dispose()


def test_init_db_preserves_existing_users_and_routes(isolated_database):
    with isolated_database() as db:
        user = WebUser(username="regular-user", password_hash="test-hash", is_admin=False)
        historical_test_user = WebUser(username="codex_test_1781652740", password_hash="test-hash", is_admin=True)
        db.add_all([user, historical_test_user])
        db.flush()
        route = TrackedRoute(origin="MOW", destination="UFA", departure_date="2030-01-01", max_price=8000, web_user_id=user.id)
        db.add(route)
        db.commit()
        user_id, route_id = user.id, route.id

    database.init_db()
    database.init_db()

    with isolated_database() as db:
        assert db.get(WebUser, user_id).is_admin is False
        assert db.get(TrackedRoute, route_id).web_user_id == user_id
        assert db.query(WebUser).filter_by(username="codex_test_1781652740").count() == 1
        assert db.query(WebUser).filter_by(username="bootstrap-admin", is_admin=True).count() == 1


def test_init_db_promotes_configured_admin_without_resetting_password(isolated_database):
    with isolated_database() as db:
        db.add(WebUser(username="bootstrap-admin", password_hash="existing-hash", is_admin=False))
        db.commit()

    database.init_db()

    with isolated_database() as db:
        user = db.query(WebUser).filter_by(username="bootstrap-admin").one()
        assert user.is_admin is True
        assert user.password_hash == "existing-hash"
