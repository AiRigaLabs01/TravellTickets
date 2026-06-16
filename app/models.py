from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class TrackedRoute(Base):
    __tablename__ = "tracked_routes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    departure_date = Column(String, nullable=False)
    return_date = Column(String, nullable=True)
    trip_type = Column(String, default="oneway")
    adult_seats = Column(Integer, default=1)
    children_seats = Column(Integer, default=0)
    infant_seats = Column(Integer, default=0)
    baggage_required = Column(Boolean, default=False)
    max_price = Column(Float, nullable=False)
    interval_minutes = Column(Integer, default=10)
    direct_only = Column(Boolean, default=False)
    airline_codes = Column(String, nullable=True)
    origin_airports = Column(String, nullable=True)
    destination_airports = Column(String, nullable=True)
    departure_time_from = Column(String, nullable=True)
    departure_time_to = Column(String, nullable=True)
    arrival_time_from = Column(String, nullable=True)
    arrival_time_to = Column(String, nullable=True)
    return_departure_time_from = Column(String, nullable=True)
    return_departure_time_to = Column(String, nullable=True)
    return_arrival_time_from = Column(String, nullable=True)
    return_arrival_time_to = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_best_price = Column(Float, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    price_checks = relationship("PriceCheck", back_populates="route", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="route", cascade="all, delete-orphan")


class PriceCheck(Base):
    __tablename__ = "price_checks"

    id = Column(Integer, primary_key=True, index=True)
    tracked_route_id = Column(Integer, ForeignKey("tracked_routes.id"), nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)
    price = Column(Float, nullable=False)
    airline = Column(String, nullable=True)
    flight_number = Column(String, nullable=True)
    gate = Column(String, nullable=True)
    origin = Column(String(3), nullable=True)
    destination = Column(String(3), nullable=True)
    origin_airport = Column(String(3), nullable=True)
    destination_airport = Column(String(3), nullable=True)
    departure_at = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)
    estimated_arrival_at = Column(DateTime, nullable=True)
    is_estimated_arrival = Column(Boolean, default=True)
    transfers = Column(Integer, default=0)
    link = Column(Text, nullable=True)
    aviasales_url = Column(Text, nullable=True)
    yandex_travel_url = Column(Text, nullable=True)
    raw_json = Column(Text, nullable=True)

    route = relationship("TrackedRoute", back_populates="price_checks")
    notifications = relationship("Notification", back_populates="price_check", cascade="all, delete-orphan")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    tracked_route_id = Column(Integer, ForeignKey("tracked_routes.id"), nullable=False)
    price_check_id = Column(Integer, ForeignKey("price_checks.id"), nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String, default="telegram")
    message = Column(Text, nullable=True)

    route = relationship("TrackedRoute", back_populates="notifications")
    price_check = relationship("PriceCheck", back_populates="notifications")
