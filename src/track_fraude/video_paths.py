from __future__ import annotations

from pathlib import Path

from track_fraude.storage import RawScope, raw_root


def resolve_video_path(
    root: Path,
    *,
    date: str,
    camera_id: str,
    store_id: str,
    group_code: str | None = "default",
    video: str | None = None,
) -> Path:
    if video:
        return Path(video)
    scope = RawScope.from_config(
        raw_root(root),
        {"group_code": group_code, "store_id": store_id},
    )
    return scope.date_dir(date) / f"{camera_id}.mp4"
