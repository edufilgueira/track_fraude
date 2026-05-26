from __future__ import annotations

from pathlib import Path

from track_fraude.pos.client import PosClient
from track_fraude.pos.file_client import FilePosClient
from track_fraude.pos.http_client import HttpPosClient

DEFAULT_POS_API_URL = "http://127.0.0.1:3099"


def create_pos_client(
    *,
    pos_root: Path | str,
    pos_api_url: str | None = None,
) -> PosClient:
    if pos_api_url:
        return HttpPosClient(pos_api_url)
    return FilePosClient(pos_root)
