from __future__ import annotations

from fastapi import FastAPI

from atlas.db.schema import init_atlas_schema
from atlas.platform.routes.jobs import build_jobs_router
from atlas.platform.settings import PlatformSettings, load_settings


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    init_atlas_schema(cfg.database.postgres_url or "")

    app = FastAPI(title="Atlas Platform API", version="0.1.0")
    app.include_router(build_jobs_router(cfg))
    return app
