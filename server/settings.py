from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
DEFAULT_SETTINGS_PATH = SERVER_DIR / "config" / "settings.yaml"


@dataclass(frozen=True)
class ServerSettings:
    app_name: str
    host: str
    port: int
    secret_key: str
    database_path: Path
    admin_username: str
    admin_password: str
    admin_display_name: str


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

    return ServerSettings(
        app_name=str(app_cfg.get("name", "track_fraude")),
        host=str(app_cfg.get("host", "127.0.0.1")),
        port=int(app_cfg.get("port", 8080)),
        secret_key=str(app_cfg.get("secret_key", "change-me")),
        database_path=db_path,
        admin_username=str(auth_cfg.get("admin_username", "admin")),
        admin_password=str(auth_cfg.get("admin_password", "admin123")),
        admin_display_name=str(auth_cfg.get("admin_display_name", "Administrador")),
    )
