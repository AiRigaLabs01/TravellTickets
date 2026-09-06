import pytest

from scripts import postgres_rehearsal


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://travelltickets_ci:pw@database.example/prod",
        "postgresql://production:pw@127.0.0.1/travelltickets_ci",
        "sqlite:///local.db",
        "",
    ],
)
def test_rehearsal_refuses_non_disposable_database(monkeypatch, url):
    monkeypatch.setenv("POSTGRES_REHEARSAL", "1")
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(SystemExit, match="Refusing"):
        postgres_rehearsal._require_disposable_database()


def test_rehearsal_requires_explicit_guard(monkeypatch):
    monkeypatch.delenv("POSTGRES_REHEARSAL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://travelltickets_ci:pw@127.0.0.1/travelltickets_ci",
    )
    with pytest.raises(SystemExit, match="Refusing"):
        postgres_rehearsal._require_disposable_database()


def test_rehearsal_accepts_only_named_local_ci_database(monkeypatch):
    monkeypatch.setenv("POSTGRES_REHEARSAL", "1")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://travelltickets_ci:pw@127.0.0.1/travelltickets_restore_ci",
    )
    postgres_rehearsal._require_disposable_database()
