from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from server.settings import ServerSettings, load_settings
from server.users import UserRepository
from track_fraude_core.db.group_repository import GroupRepository
from track_fraude_core.db.store_repository import StoreRepository

SERVER_DIR = Path(__file__).resolve().parent

_settings: ServerSettings | None = None
_store_repo: StoreRepository | None = None
_group_repo: GroupRepository | None = None
_user_repo: UserRepository | None = None
_templates: Jinja2Templates | None = None


def configure(settings_path: Path | str | None = None) -> ServerSettings:
    global _settings, _store_repo, _group_repo, _user_repo, _templates
    _settings = load_settings(settings_path)
    _store_repo = StoreRepository(_settings.database_path)
    _group_repo = GroupRepository(_settings.database_path)
    _user_repo = UserRepository(_settings.database_path)
    _templates = Jinja2Templates(directory=str(SERVER_DIR / "templates"))
    return _settings


def get_settings() -> ServerSettings:
    if _settings is None:
        return configure()
    return _settings


def get_store_repo() -> StoreRepository:
    if _store_repo is None:
        configure()
    assert _store_repo is not None
    return _store_repo


def get_group_repo() -> GroupRepository:
    if _group_repo is None:
        configure()
    assert _group_repo is not None
    return _group_repo


def get_user_repo() -> UserRepository:
    if _user_repo is None:
        configure()
    assert _user_repo is not None
    return _user_repo


def get_templates() -> Jinja2Templates:
    if _templates is None:
        configure()
    assert _templates is not None
    return _templates
