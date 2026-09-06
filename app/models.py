from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TrackedRoute(Base):
    __tablename__ = "tracked_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notification_mode: Mapped[str | None] = mapped_column(String, default="telegram")
    notification_username: Mapped[str | None] = mapped_column(String, nullable=True)
    web_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("web_users.id"), nullable=True)
    creator_source: Mapped[str | None] = mapped_column(String, default="web")
    creator_display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    creator_username: Mapped[str | None] = mapped_column(String, nullable=True)
    creator_telegram_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_date: Mapped[str] = mapped_column(String, nullable=False)
    return_date: Mapped[str | None] = mapped_column(String, nullable=True)
    trip_type: Mapped[str | None] = mapped_column(String, default="oneway")
    adult_seats: Mapped[int | None] = mapped_column(Integer, default=1)
    children_seats: Mapped[int | None] = mapped_column(Integer, default=0)
    infant_seats: Mapped[int | None] = mapped_column(Integer, default=0)
    baggage_required: Mapped[bool | None] = mapped_column(Boolean, default=False)
    max_price: Mapped[float] = mapped_column(Float, nullable=False)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, default=10)
    direct_only: Mapped[bool | None] = mapped_column(Boolean, default=False)
    airline_codes: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_airports: Mapped[str | None] = mapped_column(String, nullable=True)
    destination_airports: Mapped[str | None] = mapped_column(String, nullable=True)
    departure_time_from: Mapped[str | None] = mapped_column(String, nullable=True)
    departure_time_to: Mapped[str | None] = mapped_column(String, nullable=True)
    arrival_time_from: Mapped[str | None] = mapped_column(String, nullable=True)
    arrival_time_to: Mapped[str | None] = mapped_column(String, nullable=True)
    return_departure_time_from: Mapped[str | None] = mapped_column(String, nullable=True)
    return_departure_time_to: Mapped[str | None] = mapped_column(String, nullable=True)
    return_arrival_time_from: Mapped[str | None] = mapped_column(String, nullable=True)
    return_arrival_time_to: Mapped[str | None] = mapped_column(String, nullable=True)
    no_change_checks_count: Mapped[int | None] = mapped_column(Integer, default=0)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    last_best_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def origin_city(self) -> str:
        from app.city_codes import city_label
        return city_label(self.origin)

    @property
    def dest_city(self) -> str:
        from app.city_codes import city_label
        return city_label(self.destination)

    price_checks = relationship("PriceCheck", back_populates="route", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="route", cascade="all, delete-orphan")
    web_user = relationship("WebUser", back_populates="routes")


class WebUser(Base):
    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    routes = relationship("TrackedRoute", back_populates="web_user")


class PriceCheck(Base):
    __tablename__ = "price_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tracked_route_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracked_routes.id"), nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    matches_filters: Mapped[bool | None] = mapped_column(Boolean, default=True)
    airline: Mapped[str | None] = mapped_column(String, nullable=True)
    flight_number: Mapped[str | None] = mapped_column(String, nullable=True)
    gate: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(3), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(3), nullable=True)
    origin_airport: Mapped[str | None] = mapped_column(String(3), nullable=True)
    destination_airport: Mapped[str | None] = mapped_column(String(3), nullable=True)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_arrival_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_estimated_arrival: Mapped[bool | None] = mapped_column(Boolean, default=True)
    transfers: Mapped[int | None] = mapped_column(Integer, default=0)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    aviasales_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    yandex_travel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    route = relationship("TrackedRoute", back_populates="price_checks")
    notifications = relationship("Notification", back_populates="price_check", cascade="all, delete-orphan")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tracked_route_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracked_routes.id"), nullable=False)
    price_check_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("price_checks.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    channel: Mapped[str | None] = mapped_column(String, default="telegram")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    route = relationship("TrackedRoute", back_populates="notifications")
    price_check = relationship("PriceCheck", back_populates="notifications")
