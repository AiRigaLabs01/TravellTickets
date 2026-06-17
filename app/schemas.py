from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class RouteFormData(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    trip_type: str = "oneway"
    adult_seats: int = 1
    children_seats: int = 0
    infant_seats: int = 0
    baggage_required: bool = False
    max_price: float
    interval_minutes: int = 10
    direct_only: bool = False
    airline_codes: Optional[str] = None
    origin_airports: Optional[str] = None
    destination_airports: Optional[str] = None
    departure_time_from: Optional[str] = None
    departure_time_to: Optional[str] = None
    arrival_time_from: Optional[str] = None
    arrival_time_to: Optional[str] = None
    return_departure_time_from: Optional[str] = None
    return_departure_time_to: Optional[str] = None
    return_arrival_time_from: Optional[str] = None
    return_arrival_time_to: Optional[str] = None


class TrackedRouteCreate(BaseModel):
    title: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    max_price: float
    interval_minutes: int = 10
    direct_only: bool = False
    airline_codes: Optional[str] = None
    origin_airports: Optional[str] = None
    destination_airports: Optional[str] = None
    departure_time_from: Optional[str] = None
    departure_time_to: Optional[str] = None
    arrival_time_from: Optional[str] = None
    arrival_time_to: Optional[str] = None

    @field_validator("origin", "destination")
    @classmethod
    def uppercase_iata(cls, v: str) -> str:
        return v.strip().upper()


class TrackedRouteUpdate(BaseModel):
    title: Optional[str] = None
    max_price: Optional[float] = None
    interval_minutes: Optional[int] = None
    direct_only: Optional[bool] = None
    airline_codes: Optional[str] = None
    origin_airports: Optional[str] = None
    destination_airports: Optional[str] = None
    departure_time_from: Optional[str] = None
    departure_time_to: Optional[str] = None
    arrival_time_from: Optional[str] = None
    arrival_time_to: Optional[str] = None
    is_active: Optional[bool] = None


class TrackedRouteOut(BaseModel):
    id: int
    title: Optional[str]
    origin: str
    destination: str
    departure_date: str
    max_price: float
    interval_minutes: int
    direct_only: bool
    airline_codes: Optional[str]
    origin_airports: Optional[str]
    destination_airports: Optional[str]
    departure_time_from: Optional[str]
    departure_time_to: Optional[str]
    arrival_time_from: Optional[str]
    arrival_time_to: Optional[str]
    is_active: bool
    last_best_price: Optional[float]
    last_checked_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PriceCheckOut(BaseModel):
    id: int
    tracked_route_id: int
    checked_at: datetime
    price: float
    airline: Optional[str]
    flight_number: Optional[str]
    gate: Optional[str]
    origin_airport: Optional[str]
    destination_airport: Optional[str]
    departure_at: Optional[datetime]
    duration: Optional[int]
    estimated_arrival_at: Optional[datetime]
    is_estimated_arrival: bool
    transfers: int
    aviasales_url: Optional[str]
    yandex_travel_url: Optional[str]

    model_config = {"from_attributes": True}
