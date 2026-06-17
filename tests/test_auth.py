import app.auth as auth


def test_telegram_access_token_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")

    token = auth.create_telegram_access_token("123", "Rinat1897", 42)
    payload = auth.verify_telegram_access_token(token)

    assert payload is not None
    assert payload["chat_id"] == "123"
    assert payload["telegram_username"] == "Rinat1897"
    assert payload["route_id"] == 42


def test_telegram_access_token_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH", "configured")

    token = auth.create_telegram_access_token("123")

    assert auth.verify_telegram_access_token(token + "x") is None
