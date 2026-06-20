from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from track_fraude_core.db.database import DatabaseConfig

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
DEFAULT_SETTINGS_PATH = SERVER_DIR / "config" / "settings.yaml"


@dataclass(frozen=True)
class ServerSettings:
    app_name: str
    host: str
    port: int
    secret_key: str
    database: DatabaseConfig
    admin_username: str
    admin_password: str
    admin_display_name: str
    pipeline_mode: str = "local"
    pipeline_python: Path | None = None
    queue_url: str | None = None
    queue_name: str = "track-fraude-pipelines"

    @property
    def database_path(self) -> Path:
        if self.database.backend != "sqlite":
            raise RuntimeError("database_path disponível apenas com backend sqlite")
        assert self.database.sqlite_path is not None
        return self.database.sqlite_path

    @property
    def database_dsn(self) -> str:
        return self.database.dsn


def load_settings(path: Path | str | None = None) -> ServerSettings:
    settings_path = Path(path) if path else DEFAULT_SETTINGS_PATH
    with settings_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)

    app_cfg = raw.get("app", {})
    db_cfg = raw.get("database", {})
    auth_cfg = raw.get("auth", {})

    db_path = Path(str(db_cfg.get("path", "data/track_fraude.db")))
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()

    database = DatabaseConfig.from_settings(
        backend=db_cfg.get("backend"),
        sqlite_path=db_path,
        postgres_url=db_cfg.get("postgres_url"),
    )

    pipeline_cfg = raw.get("pipeline", {})
    pipeline_mode = str(pipeline_cfg.get("mode", "local")).strip().lower()
    pipeline_python_raw = pipeline_cfg.get("python")
    pipeline_python: Path | None = None
    if pipeline_python_raw:
        pipeline_python = Path(str(pipeline_python_raw))
        if not pipeline_python.is_absolute():
            pipeline_python = (PROJECT_ROOT / pipeline_python).resolve()

    return ServerSettings(
        app_name=str(app_cfg.get("name", "track_fraude")),
        host=str(app_cfg.get("host", "127.0.0.1")),
        port=int(app_cfg.get("port", 8080)),
        secret_key=str(app_cfg.get("secret_key", "change-me")),
        database=database,
        admin_username=str(auth_cfg.get("admin_username", "admin")),
        admin_password=str(auth_cfg.get("admin_password", "admin123")),
        admin_display_name=str(auth_cfg.get("admin_display_name", "Administrador")),
        pipeline_mode=pipeline_mode,
        pipeline_python=pipeline_python,
        queue_url=pipeline_cfg.get("queue_url"),
        queue_name=str(pipeline_cfg.get("queue_name", "track-fraude-pipelines")),
    )


def hash_secret_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_secret_key() -> str:
    return secrets.token_hex(32)
