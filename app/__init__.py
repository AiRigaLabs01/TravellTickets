from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import (
    ADMIN_USERNAME,
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
from app.database import get_db
from app.models import TrackedRoute, WebUser


_original_fastapi_init = FastAPI.__init__


def _install_admin_auth(app: FastAPI):
    templates = Jinja2Templates(directory="app/templates")

    @app.middleware("http")
    async def require_web_login(request: Request, call_next):
        public_paths = ("/login", "/logout", "/healthz", "/static/")
        if request.url.path.startswith(public_paths):
            return await call_next(request)
        if not auth_is_configured() or not get_session_user(request):
            return login_redirect(request)
        db = next(get_db())
        try:
            current_user = get_current_web_user(request, db)
            if not current_user or not current_user.is_admin:
                return login_redirect(request)
            request.state.current_user = current_user
        finally:
            db.close()
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str = "/"):
        return templates.TemplateResponse(request, "login.html", {"next_url": next})

    @app.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next_url: str = Form("/"),
        db=Depends(get_db),
    ):
        user = db.query(WebUser).filter(WebUser.username == username, WebUser.is_active == True).first()
        if auth_is_configured() and user and user.is_admin and verify_password(password, user.password_hash):
            response = RedirectResponse(next_url if next_url.startswith("/") else "/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                create_session_cookie(user.username),
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=60 * 60 * 12,
            )
            return response
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next_url": next_url, "error": "Неверный логин, пароль или нет прав администратора"},
            status_code=401,
        )

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    @app.get("/profile", response_class=HTMLResponse)
    async def profile_form(request: Request, db=Depends(get_db)):
        user = require_admin(request, db)
        return templates.TemplateResponse(request, "profile.html", {"current_user": user})

    @app.post("/profile")
    async def profile_save(
        request: Request,
        display_name: str = Form(""),
        telegram_username: str = Form(""),
        db=Depends(get_db),
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
    async def users_form(request: Request, db=Depends(get_db)):
        current_user = require_admin(request, db)
        users = db.query(WebUser).order_by(WebUser.username.asc()).all()
        return templates.TemplateResponse(request, "users.html", {"current_user": current_user, "users": users})

    @app.post("/admin/users")
    async def users_create(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        display_name: str = Form(""),
        telegram_username: str = Form(""),
        is_admin: str | None = Form(None),
        db=Depends(get_db),
    ):
        require_admin(request, db)
        username = username.strip()
        if not username or db.query(WebUser).filter(WebUser.username == username).first():
            raise HTTPException(status_code=400, detail="User already exists or username is empty")
        telegram_username = normalize_telegram_username(telegram_username)
        db.add(
            WebUser(
                username=username,
                password_hash=make_password_hash(password),
                display_name=display_name.strip() or None,
                telegram_username=telegram_username,
                telegram_chat_id=find_telegram_chat_id(db, telegram_username),
                is_admin=bool(is_admin),
            )
        )
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)

    @app.post("/admin/users/{user_id}/toggle")
    async def users_toggle(request: Request, user_id: int, db=Depends(get_db)):
        current_user = require_admin(request, db)
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user or user.id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot update this user")
        user.is_active = not user.is_active
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)

    @app.post("/admin/users/{user_id}/password")
    async def users_password(request: Request, user_id: int, password: str = Form(...), db=Depends(get_db)):
        require_admin(request, db)
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404)
        user.password_hash = make_password_hash(password)
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)


def _patched_fastapi_init(self, *args, **kwargs):
    _original_fastapi_init(self, *args, **kwargs)
    _install_admin_auth(self)


if getattr(FastAPI.__init__, "__name__", "") != "_patched_fastapi_init":
    FastAPI.__init__ = _patched_fastapi_init
