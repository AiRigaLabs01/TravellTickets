from fastapi.testclient import TestClient

import app.auth as auth
from app.main import app


def test_locations_api_v1_returns_list(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/api/v1/locations/search?q=Москва")

    assert response.status_code == 200


def test_health_endpoint_shape(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
