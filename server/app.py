from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from server.auth import get_current_user_id
from server.dependencies import configure, get_settings, get_user_repo
from server.routes import auth, cameras, groups, stores
from track_fraude_core.db import init_database

SERVER_DIR = Path(__file__).resolve().parent

PUBLIC_PATHS = {"/login", "/health"}


def create_app(settings_path: Path | str | None = None) -> FastAPI:
    settings = configure(settings_path)
    init_database(settings.database_path)

    user_repo = get_user_repo()
    user_repo.seed_admin(
        username=settings.admin_username,
        password=settings.admin_password,
        display_name=settings.admin_display_name,
    )

    app = FastAPI(title=f"{settings.app_name} — Painel")

    # SessionMiddleware deve ser registrado DEPOIS do auth abaixo (insert at 0),
    # para ficar por fora e popular request.session antes da checagem de login.
    @app.middleware("http")
    async def require_authentication(request: Request, call_next):
        path = request.url.path
        if path.startswith("/static") or path in PUBLIC_PATHS:
            return await call_next(request)
        if get_current_user_id(request) is None:
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="track_fraude_session",
        max_age=60 * 60 * 8,
        same_site="lax",
    )

    @app.middleware("http")
    async def disable_html_cache(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=str(SERVER_DIR / "static")), name="static")

    @app.get("/")
    async def home() -> RedirectResponse:
        return RedirectResponse(url="/groups", status_code=302)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "web"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    app.include_router(auth.router)
    app.include_router(groups.router)
    app.include_router(stores.router)
    app.include_router(cameras.router)

    return app
