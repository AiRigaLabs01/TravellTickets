from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.auth import normalize_telegram_username
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
        username = normalize_telegram_username(payload.get("telegram_username"))
        filters = [TrackedRoute.telegram_chat_id == chat_id]
        if username:
            filters.extend(
                [
                    TrackedRoute.creator_username == username,
                    TrackedRoute.notification_username == username,
                ]
            )
        return self.db.query(TrackedRoute).filter(or_(*filters))

    def latest_check(self, route_id: int) -> PriceCheck | None:
        return (
            self.db.query(PriceCheck)
            .filter(PriceCheck.tracked_route_id == route_id)
            .order_by(PriceCheck.checked_at.desc())
            .first()
        )
