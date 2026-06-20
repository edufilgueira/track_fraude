from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_DB_PATH = Path("data/track_fraude.db")
DEFAULT_POSTGRES_URL = (
    "postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude"
)

Backend = Literal["sqlite", "postgres"]


@dataclass(frozen=True)
class DatabaseConfig:
    backend: Backend
    sqlite_path: Path | None = None
    postgres_url: str | None = None

    @property
    def dsn(self) -> str:
        if self.backend == "postgres":
            if not self.postgres_url:
                raise ValueError("postgres_url é obrigatório para backend postgres")
            return self.postgres_url
        if self.sqlite_path is None:
            raise ValueError("sqlite_path é obrigatório para backend sqlite")
        return str(self.sqlite_path.resolve())

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgres"

    @classmethod
    def sqlite(cls, path: Path | str | None = None) -> DatabaseConfig:
        resolved = Path(path) if path else DEFAULT_DB_PATH
        if not resolved.is_absolute():
            resolved = resolved.resolve()
        return cls(backend="sqlite", sqlite_path=resolved)

    @classmethod
    def postgres(cls, url: str) -> DatabaseConfig:
        return cls(backend="postgres", postgres_url=url.strip())

    @classmethod
    def from_dsn(cls, dsn: str | Path) -> DatabaseConfig:
        text = str(dsn).strip()
        if text.startswith("postgresql://") or text.startswith("postgres://"):
            return cls.postgres(text)
        return cls.sqlite(Path(text))

    @classmethod
    def from_settings(
        cls,
        *,
        backend: str | None = None,
        sqlite_path: Path | str | None = None,
        postgres_url: str | None = None,
    ) -> DatabaseConfig:
        env_url = os.getenv("TRACK_FRAUDE_DATABASE_URL", "").strip()
        if env_url:
            return cls.from_dsn(env_url)

        normalized_backend = str(backend or "sqlite").strip().lower()
        if normalized_backend == "postgres":
            url = (postgres_url or DEFAULT_POSTGRES_URL).strip()
            return cls.postgres(url)
        return cls.sqlite(sqlite_path)


def resolve_database(source: DatabaseConfig | Path | str | None = None) -> DatabaseConfig:
    if isinstance(source, DatabaseConfig):
        return source
    if source is None:
        return DatabaseConfig.from_settings()
    return DatabaseConfig.from_dsn(source)
