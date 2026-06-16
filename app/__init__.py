from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import auth_is_configured, create_session_cookie, get_session_user, login_redirect, verify_password
from app.auth import ADMIN_USERNAME, SESSION_COOKIE_NAME


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
    ):
        if auth_is_configured() and username == ADMIN_USERNAME and verify_password(password):
            response = RedirectResponse(next_url if next_url.startswith("/") else "/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                create_session_cookie(username),
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=60 * 60 * 12,
            )
            return response
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next_url": next_url, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response


def _patched_fastapi_init(self, *args, **kwargs):
    _original_fastapi_init(self, *args, **kwargs)
    _install_admin_auth(self)


if getattr(FastAPI.__init__, "__name__", "") != "_patched_fastapi_init":
    FastAPI.__init__ = _patched_fastapi_init
