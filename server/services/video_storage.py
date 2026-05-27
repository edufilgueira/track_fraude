from __future__ import annotations

import shutil
from pathlib import Path

from server.settings import PROJECT_ROOT


def raw_video_path(*, date: str, camera_id: str) -> Path:
    return PROJECT_ROOT / "data" / "raw" / "video" / date.strip() / f"{camera_id.strip()}.mp4"


def raw_video_relpath(*, date: str, camera_id: str) -> str:
    return f"data/raw/video/{date.strip()}/{camera_id.strip()}.mp4"


def save_raw_video(*, date: str, camera_id: str, content: bytes) -> Path:
    """Persiste MP4 em data/raw/video/{date}/{camera_id}.mp4 (nunca remove)."""
    dest = raw_video_path(date=date, camera_id=camera_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def copy_raw_video(*, date: str, camera_id: str, source: Path) -> Path:
    """Copia MP4 validado para data/raw/video/{date}/{camera_id}.mp4."""
    dest = raw_video_path(date=date, camera_id=camera_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest
