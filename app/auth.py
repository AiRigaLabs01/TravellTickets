import base64
import hashlib
import hmac
import os
import time
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

SESSION_TTL_SECONDS = 60 * 60 * 12
HASH_ITERATIONS = 260_000
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "travelltickets_session")


def make_password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ITERATIONS)
    encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, stored_hash: str = ADMIN_PASSWORD_HASH) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        actual = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def _sign(payload: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def auth_is_configured() -> bool:
    return bool(ADMIN_USERNAME and ADMIN_PASSWORD_HASH and SESSION_SECRET)


def create_session_cookie(username: str) -> str:
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    nonce = base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    payload = f"{username}:{expires_at}:{nonce}"
    return f"{payload}:{_sign(payload)}"


def get_session_user(request: Request) -> str | None:
    if not auth_is_configured():
        return None
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    try:
        username, expires_at, nonce, signature = cookie.rsplit(":", 3)
        payload = f"{username}:{expires_at}:{nonce}"
        if int(expires_at) < int(time.time()):
            return None
        if not hmac.compare_digest(_sign(payload), signature):
            return None
        return username
    except (TypeError, ValueError):
        return None


def normalize_telegram_username(value: str | None) -> str | None:
    username = (value or "").strip().lstrip("@")
    return username or None


def get_current_web_user(request: Request, db: Session):
    from app.models import WebUser

    username = get_session_user(request)
    if not username:
        return None
    return db.query(WebUser).filter(WebUser.username == username, WebUser.is_active == True).first()


def require_admin(request: Request, db: Session):
    user = get_current_web_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def find_telegram_chat_id(db: Session, telegram_username: str | None) -> str | None:
    from app.models import TrackedRoute

    username = normalize_telegram_username(telegram_username)
    if not username:
        return None
    route = (
        db.query(TrackedRoute)
        .filter(TrackedRoute.creator_username == username, TrackedRoute.telegram_chat_id.isnot(None))
        .order_by(TrackedRoute.created_at.desc())
        .first()
    )
    return route.telegram_chat_id if route else None


def login_redirect(request: Request) -> RedirectResponse:
    next_url = request.url.path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)
