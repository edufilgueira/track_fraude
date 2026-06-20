from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from server.settings import get_data_root

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_group_code(group_code: str | None) -> str:
    return (group_code or "default").strip() or "default"


def raw_store_dir(*, group_code: str | None, store_id: str) -> Path:
    return (
        get_data_root()
        / "raw"
        / _normalize_group_code(group_code)
        / store_id.strip()
    )


def raw_day_dir(*, group_code: str | None, store_id: str, date: str) -> Path:
    return raw_store_dir(group_code=group_code, store_id=store_id) / date.strip()


def raw_video_path(
    *,
    group_code: str | None,
    store_id: str,
    date: str,
    camera_id: str,
) -> Path:
    return raw_day_dir(
        group_code=group_code,
        store_id=store_id,
        date=date,
    ) / f"{camera_id.strip()}.mp4"


def raw_video_relpath(
    *,
    group_code: str | None,
    store_id: str,
    date: str,
    camera_id: str,
) -> str:
    group = _normalize_group_code(group_code)
    return (
        f"data/raw/{group}/{store_id.strip()}/{date.strip()}/{camera_id.strip()}.mp4"
    )


def save_raw_video(
    *,
    group_code: str | None,
    store_id: str,
    date: str,
    camera_id: str,
    content: bytes,
) -> Path:
    """Persiste MP4 em data/raw/{group}/{store}/{date}/{camera_id}.mp4 (nunca remove)."""
    dest = raw_video_path(
        group_code=group_code,
        store_id=store_id,
        date=date,
        camera_id=camera_id,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def copy_raw_video(
    *,
    group_code: str | None,
    store_id: str,
    date: str,
    camera_id: str,
    source: Path,
) -> Path:
    """Copia MP4 validado para data/raw/{group}/{store}/{date}/{camera_id}.mp4."""
    dest = raw_video_path(
        group_code=group_code,
        store_id=store_id,
        date=date,
        camera_id=camera_id,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def list_raw_import_dates(*, group_code: str | None, store_id: str) -> list[str]:
    return raw_store_dir_status(group_code=group_code, store_id=store_id)["dates"]


def raw_store_dir_status(*, group_code: str | None, store_id: str) -> dict:
    store_dir = raw_store_dir(group_code=group_code, store_id=store_id)
    if not store_dir.is_dir():
        return {
            "store_dir_exists": False,
            "data_root": get_data_root().as_posix(),
            "entries": [],
            "dates": [],
        }

    entries: list[dict[str, str | bool]] = []
    dates: list[str] = []
    for child in sorted(store_dir.iterdir(), key=lambda item: item.name):
        entries.append({"name": child.name, "is_dir": child.is_dir()})
        if child.is_dir() and _DATE_DIR_RE.match(child.name):
            dates.append(child.name)

    return {
        "store_dir_exists": True,
        "data_root": get_data_root().as_posix(),
        "entries": entries,
        "dates": sorted(dates, reverse=True),
    }


def format_date_br(iso_date: str) -> str:
    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
    return parsed.strftime("%d/%m/%Y")
