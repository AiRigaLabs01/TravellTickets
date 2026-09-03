from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth as auth
from app.database import Base, get_db
from app.main import app
from app.models import TrackedRoute
from app.repositories import RouteRepository
from app.telegram_bot import owned_route, owned_routes


@pytest.fixture
def routes_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for chat, username in [("111", "old_name"), ("222", "recycled_name"), (None, "recycled_name"), ("111", "old_name")]:
            db.add(TrackedRoute(origin="MOW", destination="UFA", departure_date="2030-01-01",
                                max_price=8000, telegram_chat_id=chat, creator_username=username,
                                notification_username=username))
        db.commit()
        monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
        monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = lambda: db
        yield db
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
    engine.dispose()


def test_telegram_username_does_not_grant_another_chat_access(routes_db):
    repo = RouteRepository(routes_db)
    rows = repo.query_for_telegram_payload({"chat_id": "111", "telegram_username": "recycled_name"}).all()
    assert [r.id for r in rows] == [1, 4]
    assert repo.query_for_telegram_payload({"telegram_username": "recycled_name"}).count() == 0


def test_route_token_cannot_list_other_routes(routes_db):
    repo = RouteRepository(routes_db)
    assert repo.query_for_telegram_payload({"chat_id": "111", "route_id": 2}).count() == 0
    assert repo.query_for_telegram_payload({"chat_id": "111", "route_id": 1}).one().id == 1


def test_bot_ownership_uses_chat_not_recycled_username(routes_db):
    message = SimpleNamespace(chat=SimpleNamespace(id=111), from_user=SimpleNamespace(username="recycled_name"))
    assert [r.id for r in owned_routes(routes_db, message).all()] == [1, 4]
    assert owned_route(routes_db, message, 2) is None
    assert owned_route(routes_db, message, 1).id == 1


@pytest.mark.parametrize("path", ["/tg/monitorings", "/tg/route/1"])
def test_private_pages_do_not_expose_access_token_to_third_parties(routes_db, path):
    token = auth.create_telegram_access_token("111", "old_name")
    response = TestClient(app).get(path, params={"token": token})
    assert response.status_code == 200
    assert "emrldco.com" not in response.text
    assert "emrldco.com" not in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_foreign_route_is_not_visible_via_recycled_username(routes_db):
    token = auth.create_telegram_access_token("111", "recycled_name")
    response = TestClient(app).get("/tg/route/2", params={"token": token})
    assert response.status_code == 404


def test_route_scoped_token_cannot_expand_access_through_list_page(routes_db):
    token = auth.create_telegram_access_token("111", "old_name", route_id=1)
    client = TestClient(app)
    response = client.get("/tg/monitorings", params={"token": token})
    assert response.status_code == 200
    assert "/tg/route/1?" in response.text
    assert "/tg/route/4?" not in response.text
    assert client.get("/tg/route/4", params={"token": token}).status_code == 404


def test_legacy_proxy_does_not_override_private_referrer_policy():
    config = Path("haproxy/haproxy.cfg").read_text()
    assert "http-response set-header Referrer-Policy no-referrer\n" in config
