from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.date_utils import format_msk_time, to_msk
from app.models import Base, TrackedRoute


def test_typed_models_preserve_postgres_schema():
    ddl = "\n".join(
        str(CreateTable(table).compile(dialect=dialect())) + "\n"
        + "\n".join(str(CreateIndex(index).compile(dialect=dialect())) for index in sorted(table.indexes, key=lambda i: i.name))
        for table in Base.metadata.sorted_tables
    )
    expected = Path("tests/fixtures/schema_before_typing.sql").read_text()
    assert " ".join(ddl.split()) == " ".join(expected.split())


def test_date_formatters_accept_iso_strings_and_invalid_input():
    assert to_msk("2030-01-01T12:00:00+00:00") == to_msk(datetime(2030, 1, 1, 12, tzinfo=timezone.utc))
    assert format_msk_time("2030-01-01T12:00:00+00:00") == "15:00 МСК"
    assert to_msk("invalid") is None
    assert format_msk_time("invalid") == "invalid"
    assert to_msk(None) is None


def test_city_labels_are_unmapped_properties():
    route = TrackedRoute(origin="MOW", destination="UFA")
    assert route.origin_city and route.dest_city
    assert "origin_city" not in TrackedRoute.__table__.columns
    assert "dest_city" not in TrackedRoute.__table__.columns
