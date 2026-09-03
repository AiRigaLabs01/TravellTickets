import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE_NAME,
    auth_is_configured,
    create_session_cookie,
    find_telegram_chat_id,
    get_current_web_user,
    get_session_user,
    login_redirect,
    make_password_hash,
    normalize_telegram_username,
    require_admin,
    verify_password,
)
from app.database import SessionLocal, get_db
from app.config import APP_BASE_URL
from app.models import TrackedRoute, WebUser

MAX_REQUEST_BYTES = 1024 * 1024
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 120
RATE_LIMIT_LOGIN_MAX_REQUESTS = 20
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def problem_response(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
    }
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=status_code, media_type="application/problem+json")


def _client_key(request: Request) -> str:
    # Uvicorn applies forwarded headers only for FORWARDED_ALLOW_IPS peers.
    host = request.client.host if request.client else "unknown"
    path_group = "login" if request.url.path.startswith("/login") else request.url.path.split("/", 3)[1]
    return f"{host}:{path_group}"


def _safe_next_url(value: str) -> str:
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        return "/"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "/"
    path = unquote(parts.path)
    if (parts.scheme or parts.netloc or not path.startswith("/") or path.startswith("//")
            or "\\" in path or "%" in path or any(ord(c) < 32 or ord(c) == 127 for c in path)):
        return "/"
    return value


def _rate_limited(request: Request) -> bool:
    if not request.url.path.startswith(("/login", "/tg/", "/api/")):
        return False
    now = time.monotonic()
    bucket = _rate_buckets[_client_key(request)]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    limit = RATE_LIMIT_LOGIN_MAX_REQUESTS if request.url.path.startswith("/login") else RATE_LIMIT_MAX_REQUESTS
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _is_public_path(path: str) -> bool:
    if path == "/":
        return True
    if path.startswith(("/api/v1/locations/search", "/api/locations/search")):
        return True
    return path.startswith(("/public", "/login", "/logout", "/health", "/healthz", "/static/", "/tg/"))


def _allows_partner_script(path: str) -> bool:
    return path in ("/", "/public")


def _add_security_headers(response: Response, path: str) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if path.startswith("/tg/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    allow_partner = _allows_partner_script(path)
    script_src = "'self' 'unsafe-inline' https://emrldco.com" if allow_partner else "'self'"
    style_src = (
        "'self' 'unsafe-inline' https://emrldco.com https://fonts.googleapis.com"
        if allow_partner
        else "'self' 'unsafe-inline'"
    )
    font_src = "'self' https://fonts.gstatic.com" if allow_partner else "'self'"
    connect_src = (
        "'self' https://emrldco.com https://sentry.avs.io https://www.travelpayouts.com"
        if allow_partner
        else "'self'"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        f"default-src 'self'; script-src {script_src}; style-src {style_src}; "
        f"img-src 'self' data: https:; font-src {font_src}; connect-src {connect_src}; "
        "frame-ancestors 'none'; base-uri 'self'",
    )
    return response


def install_web_admin(app: FastAPI) -> None:
    templates = Jinja2Templates(directory="app/templates")

    @app.exception_handler(HTTPException)
    async def http_problem_handler(request: Request, exc: HTTPException) -> Response:
        return problem_response(exc.status_code, str(exc.detail or "HTTP error"))

    @app.middleware("http")
    async def security_and_admin_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            content_length = int(request.headers.get("content-length") or 0)
            if content_length < 0:
                raise ValueError
        except ValueError:
            return _add_security_headers(problem_response(400, "Invalid Content-Length"), request.url.path)
        if content_length > MAX_REQUEST_BYTES:
            return _add_security_headers(problem_response(413, "Request Entity Too Large"), request.url.path)
        if _rate_limited(request):
            return _add_security_headers(problem_response(429, "Too Many Requests"), request.url.path)
        if not _is_public_path(request.url.path):
            if not auth_is_configured() or not get_session_user(request):
                return login_redirect(request)
            db = SessionLocal()
            try:
                current_user = get_current_web_user(request, db)
                if not current_user or not current_user.is_admin:
                    return login_redirect(request)
                request.state.current_user = current_user
            finally:
                db.close()
        response = await call_next(request)
        return _add_security_headers(response, request.url.path)

    @app.get("/health/")
    async def health(db: Session = Depends(get_db)) -> dict[str, str]:
        db.execute(text("select 1"))
        return {"status": "ok", "database": "ok", "auth": "configured" if auth_is_configured() else "not_configured"}

    @app.get("/healthz")
    async def healthz(db: Session = Depends(get_db)) -> dict[str, str]:
        db.execute(text("select 1"))
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str = "/"):
        return templates.TemplateResponse(request, "login.html", {"next_url": _safe_next_url(next)})

    @app.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next_url: str = Form("/"),
        db: Session = Depends(get_db),
    ):
        user = db.query(WebUser).filter(WebUser.username == username, WebUser.is_active == True).first()
        if auth_is_configured() and user and user.is_admin and verify_password(password, user.password_hash):
            response = RedirectResponse(_safe_next_url(next_url), status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                create_session_cookie(user.username),
                httponly=True,
                secure=request.url.scheme == "https" or APP_BASE_URL.lower().startswith("https://"),
                samesite="lax",
                max_age=60 * 60 * 12,
            )
            return response
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next_url": _safe_next_url(next_url), "error": "Неверный логин, пароль или нет прав администратора"},
            status_code=401,
        )

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    @app.get("/profile", response_class=HTMLResponse)
    async def profile_form(request: Request, db: Session = Depends(get_db)):
        user = require_admin(request, db)
        return templates.TemplateResponse(request, "profile.html", {"current_user": user})

    @app.post("/profile")
    async def profile_save(
        request: Request,
        display_name: str = Form(""),
        telegram_username: str = Form(""),
        db: Session = Depends(get_db),
    ):
        user = require_admin(request, db)
        user.display_name = display_name.strip() or None
        user.telegram_username = normalize_telegram_username(telegram_username)
        user.telegram_chat_id = find_telegram_chat_id(db, user.telegram_username) or user.telegram_chat_id
        db.query(TrackedRoute).filter(TrackedRoute.web_user_id == user.id).update(
            {
                TrackedRoute.creator_display_name: user.display_name or user.username,
                TrackedRoute.creator_username: user.telegram_username,
            },
            synchronize_session=False,
        )
        db.commit()
        return RedirectResponse("/profile", status_code=303)

    @app.get("/admin/users", response_class=HTMLResponse)
    async def users_form(request: Request, db: Session = Depends(get_db)):
        current_user = require_admin(request, db)
        users = db.query(WebUser).order_by(WebUser.username.asc()).all()
        return templates.TemplateResponse(request, "users.html", {"current_user": current_user, "users": users})

    @app.post("/admin/users/{user_id}/toggle")
    async def users_toggle(request: Request, user_id: int, db: Session = Depends(get_db)):
        current_user = require_admin(request, db)
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user or user.id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot update this user")
        user.is_active = not user.is_active
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)

    @app.post("/admin/users/{user_id}/password")
    async def users_password(
        request: Request,
        user_id: int,
        password: str = Form(...),
        db: Session = Depends(get_db),
    ):
        require_admin(request, db)
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404)
        user.password_hash = make_password_hash(password)
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)
