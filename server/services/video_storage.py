from __future__ import annotations

from pathlib import Path

from server.settings import PROJECT_ROOT


def raw_video_path(*, date: str, camera_id: str) -> Path:
    return PROJECT_ROOT / "data" / "raw" / "video" / date.strip() / f"{camera_id.strip()}.mp4"


def raw_video_relpath(*, date: str, camera_id: str) -> str:
    return f"data/raw/video/{date.strip()}/{camera_id.strip()}.mp4"
