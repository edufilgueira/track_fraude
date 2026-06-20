from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from atlas.db.repositories import ApiKeyRepository
from atlas.platform.settings import PlatformSettings, hash_api_key


@dataclass(frozen=True)
class AuthContext:
    api_key_name: str
    scopes: list[str]


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    alt = request.headers.get("X-Atlas-Api-Key", "").strip()
    return alt or None


def authenticate_request(request: Request, settings: PlatformSettings) -> AuthContext:
    if not settings.require_api_key:
        return AuthContext(api_key_name="anonymous", scopes=["*"])

    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="API key ausente")

    repo = ApiKeyRepository(settings.database_dsn)
    record = repo.get_by_hash(hash_api_key(token))
    if record is None:
        raise HTTPException(status_code=401, detail="API key inválida")

    return AuthContext(api_key_name=record.name, scopes=record.scopes)
