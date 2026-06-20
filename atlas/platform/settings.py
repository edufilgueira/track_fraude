from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from track_fraude_core.db.database import DatabaseConfig


@dataclass(frozen=True)
class PlatformSettings:
    host: str
    port: int
    database: DatabaseConfig
    rabbitmq_url: str
    require_api_key: bool

    @property
    def database_dsn(self) -> str:
        return self.database.dsn


def load_settings() -> PlatformSettings:
    postgres_url = (
        os.getenv("ATLAS_DATABASE_URL", "").strip()
        or os.getenv("TRACK_FRAUDE_DATABASE_URL", "").strip()
    )
    if not postgres_url:
        raise RuntimeError("ATLAS_DATABASE_URL ou TRACK_FRAUDE_DATABASE_URL é obrigatório")

    rabbitmq_url = os.getenv("ATLAS_RABBITMQ_URL", "").strip()
    if not rabbitmq_url:
        raise RuntimeError("ATLAS_RABBITMQ_URL é obrigatório")

    database = DatabaseConfig.from_settings(
        backend="postgres",
        postgres_url=postgres_url,
    )
    require_api_key = os.getenv("ATLAS_REQUIRE_API_KEY", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }

    return PlatformSettings(
        host=os.getenv("ATLAS_HOST", "0.0.0.0"),
        port=int(os.getenv("ATLAS_PORT", "8090")),
        database=database,
        rabbitmq_url=rabbitmq_url,
        require_api_key=require_api_key,
    )


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
