from __future__ import annotations

from pathlib import Path


def resolve_video_path(
    root: Path,
    *,
    date: str,
    camera_id: str,
    video: str | None,
) -> Path:
    if video:
        return Path(video)
    return root / "data" / "raw" / "video" / date / f"{camera_id}.mp4"
