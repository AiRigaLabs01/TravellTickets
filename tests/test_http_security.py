import logging
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.auth as auth
import app.web_admin as web
from app.database import get_db
from app.main import app


@pytest.fixture
def login_client(monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(web, "verify_password", lambda *_: True)
    user = SimpleNamespace(username="admin", password_hash="test-hash", is_admin=True)
    query = SimpleNamespace(first=lambda: user)
    db = SimpleNamespace(query=lambda *_: SimpleNamespace(filter=lambda *_: query))
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    web._rate_buckets.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        web._rate_buckets.clear()


@pytest.mark.parametrize("target", ["//evil.example", "///evil.example", "////evil.example", "/\\evil.example", "https://evil.example", "/\n/evil.example", "/%2f/evil.example"])
def test_login_rejects_external_or_ambiguous_redirect(login_client, target):
    response = login_client.post("/login", data={"username": "admin", "password": "test", "next_url": target}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_login_preserves_local_redirect(login_client):
    response = login_client.post("/login", data={"username": "admin", "password": "test", "next_url": "/profile?tab=1"}, follow_redirects=False)
    assert response.headers["location"] == "/profile?tab=1"


def test_https_public_url_keeps_cookie_secure_without_trusting_forwarded_header(login_client, monkeypatch):
    monkeypatch.setattr(web, "APP_BASE_URL", "https://tickets.example")
    response = login_client.post("/login", data={"username": "admin", "password": "test"}, follow_redirects=False)
    assert "; Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("length", ["invalid", "-1"])
def test_invalid_content_length_is_bad_request(login_client, length):
    response = login_client.get("/tg/monitorings?token=invalid", headers={"Content-Length": length})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


def test_forwarded_header_cannot_evade_login_limit(login_client):
    for number in range(web.RATE_LIMIT_LOGIN_MAX_REQUESTS):
        assert login_client.get("/login", headers={"X-Forwarded-For": f"192.0.2.{number}"}).status_code == 200
    assert login_client.get("/login", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 429


@pytest.mark.parametrize("peer,expected", [("10.0.0.2", "192.0.2.1"), ("10.0.0.3", "10.0.0.3")])
def test_only_configured_proxy_can_supply_client_address(peer, expected):
    async def echo(scope, receive, send):
        from starlette.responses import JSONResponse
        await JSONResponse({"key": web._client_key(Request(scope)), "scheme": scope["scheme"]})(scope, receive, send)

    client = TestClient(ProxyHeadersMiddleware(echo, trusted_hosts=["10.0.0.2"]), client=(peer, 1234))
    response = client.get("/login", headers={"X-Forwarded-For": "192.0.2.1", "X-Forwarded-Proto": "https"})
    assert response.json()["key"] == f"{expected}:login"
    assert response.json()["scheme"] == ("https" if peer == "10.0.0.2" else "http")


def test_log_formatter_redacts_urls_secrets_and_exception(monkeypatch):
    from app.log_security import RedactingFormatter

    fake_bot = "123456789:" + "z" * 35
    monkeypatch.setenv("SESSION_SECRET", "example-session-value")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(logging.Formatter("%(levelname)s %(message)s")))
    logger = logging.Logger("test-security")
    logger.addHandler(handler)
    logger.warning("GET %s HTTP/1.1", "/tg/monitorings?token=private-link&other=1")
    logger.info("POST https://api.telegram.org/bot%s/sendMessage", fake_bot)
    try:
        raise ValueError("example-session-value https://test.example/?token=private-error")
    except ValueError:
        logger.exception("failed")
    output = stream.getvalue()
    for secret in [fake_bot, "private-link", "private-error", "example-session-value"]:
        assert secret not in output
    assert "ValueError" in output
    assert "/tg/monitorings" in output
    assert "[REDACTED]" in output


def test_uvicorn_access_formatter_keeps_status_but_not_query():
    from app.log_security import RedactingFormatter
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1", "GET", "/tg/monitorings?token=private-link", "1.1", 200), None)
    output = RedactingFormatter(AccessFormatter('%(request_line)s %(status_code)s', use_colors=False)).format(record)
    assert "private-link" not in output
    assert "200" in output


def test_proxy_config_does_not_log_query_or_append_untrusted_forwarding():
    config = Path("haproxy/haproxy.cfg").read_text()
    assert "option forwardfor" not in config
    assert "http-request set-header X-Forwarded-For %[src]" in config
    assert "option httplog" not in config
    assert "%HP" in config
    assert "%HU" not in config and "%HQ" not in config
