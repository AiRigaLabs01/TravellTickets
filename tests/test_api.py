from pathlib import Path

from fastapi.testclient import TestClient

import app.auth as auth
from app.main import app


def test_locations_api_v1_returns_list(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/api/v1/locations/search?q=Москва")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    values = {item["value"] for item in response.json()}
    assert {"MOW", "SVO", "VKO", "DME"}.issubset(values)


def test_root_is_public_for_anonymous_users(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "script.src = 'https://emrldco.com/NTQwNjU5.js?t=540659';" in response.text
    assert "document.head.appendChild(script);" in response.text
    assert "nowprocket" in response.text
    assert "data-noptimize=\"1\"" in response.text
    assert "script-src 'self' 'unsafe-inline' https://emrldco.com" in response.headers["content-security-policy"]
    assert (
        "style-src 'self' 'unsafe-inline' https://emrldco.com https://fonts.googleapis.com"
        in response.headers["content-security-policy"]
    )
    assert "font-src 'self' https://fonts.gstatic.com" in response.headers["content-security-policy"]
    assert (
        "connect-src 'self' https://emrldco.com https://sentry.avs.io https://www.travelpayouts.com"
        in response.headers["content-security-policy"]
    )
    assert "/login" in response.text


def test_login_page_does_not_include_partner_script(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    assert "NTQwNjU5.js" not in response.text
    assert "script-src 'self';" in response.headers["content-security-policy"]
    assert "style-src 'self' 'unsafe-inline';" in response.headers["content-security-policy"]
    assert "font-src 'self';" in response.headers["content-security-policy"]
    assert "connect-src 'self';" in response.headers["content-security-policy"]


def test_health_endpoint_shape(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    client = TestClient(app)

    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_route_form_uses_external_script_without_inline_handlers() -> None:
    html = Path("app/templates/route_form.html").read_text(encoding="utf-8")

    assert '<script src="/static/route-form.js" defer></script>' in html
    assert "partner_script.html" not in html
    assert "<script>" not in html
    assert "onclick=" not in html
    assert "onchange=" not in html
    assert "onsubmit=" not in html
