import pytest

from scripts.check_secrets import findings, forbidden_path


@pytest.mark.parametrize("path", [".env", ".env.prod", "operator/access", ".ssh/id_ed25519", "haproxy/certs/site.pem"])
def test_secret_guard_rejects_sensitive_paths(path):
    assert forbidden_path(path)


@pytest.mark.parametrize("path", [".env.example", "app/config.py", "tests/test_auth.py"])
def test_secret_guard_allows_safe_paths(path):
    assert not forbidden_path(path)


def test_secret_guard_detects_values_without_returning_them():
    fake_token = b"123456789:" + b"a" * 35
    assert findings(fake_token) == [("telegram-token", 1)]
    fake_key = b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----"
    assert findings(b"header\n" + fake_key) == [("private-key", 2)]
    assert findings(b'TRAVELPAYOUTS_TOKEN=""\n') == []
