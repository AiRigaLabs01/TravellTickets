from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_postgres() -> bool:
    return engine.dialect.name.startswith("postgres")


def _ensure_tracked_route_columns():
    """Small MVP migration helper for SQLite/Postgres-like dev DBs without Alembic."""
    inspector = inspect(engine)
    if "tracked_routes" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("tracked_routes")}
    boolean_default = "BOOLEAN DEFAULT false" if _is_postgres() else "BOOLEAN DEFAULT 0"
    columns = {
        "trip_type": "VARCHAR DEFAULT 'oneway'",
        "adult_seats": "INTEGER DEFAULT 1",
        "children_seats": "INTEGER DEFAULT 0",
        "infant_seats": "INTEGER DEFAULT 0",
        "baggage_required": boolean_default,
        "return_departure_time_from": "VARCHAR",
        "return_departure_time_to": "VARCHAR",
        "return_arrival_time_from": "VARCHAR",
        "return_arrival_time_to": "VARCHAR",
    }
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE tracked_routes ADD COLUMN {name} {ddl}"))


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_tracked_route_columns()
