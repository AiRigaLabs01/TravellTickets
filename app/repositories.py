from sqlalchemy import false
from sqlalchemy.orm import Query, Session

from app.models import PriceCheck, TrackedRoute, WebUser


class RouteRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def query_for_web_user(self, user: WebUser | None) -> Query:
        query = self.db.query(TrackedRoute)
        if user and not user.is_admin:
            query = query.filter(TrackedRoute.web_user_id == user.id)
        return query

    def query_for_telegram_payload(self, payload: dict) -> Query:
        chat_id = str(payload.get("chat_id") or "")
        query = self.db.query(TrackedRoute)
        if not chat_id:
            return query.filter(false())
        # Usernames can be reassigned; only the verified chat binding grants access.
        query = query.filter(TrackedRoute.telegram_chat_id == chat_id)
        if payload.get("route_id") is not None:
            query = query.filter(TrackedRoute.id == payload["route_id"])
        return query

    def latest_check(self, route_id: int) -> PriceCheck | None:
        return (
            self.db.query(PriceCheck)
            .filter(PriceCheck.tracked_route_id == route_id)
            .order_by(PriceCheck.checked_at.desc())
            .first()
        )
