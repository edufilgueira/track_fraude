from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.settings import PROJECT_ROOT, SERVER_DIR

EDITOR_FRAMES_ROOT = SERVER_DIR / "upload" / "editor_frames"
# Legado local (antes ficava em data/); migrado automaticamente para EDITOR_FRAMES_ROOT.
LEGACY_DATA_FRAMES_ROOT = PROJECT_ROOT / "data" / "editor_frames"


def editor_frame_dir(*, store_db_id: int, camera_db_id: int) -> Path:
    return EDITOR_FRAMES_ROOT / str(store_db_id) / str(camera_db_id)


def editor_frame_jpeg_path(*, store_db_id: int, camera_db_id: int) -> Path:
    return editor_frame_dir(store_db_id=store_db_id, camera_db_id=camera_db_id) / "frame.jpg"


def editor_frame_meta_path(*, store_db_id: int, camera_db_id: int) -> Path:
    return editor_frame_dir(store_db_id=store_db_id, camera_db_id=camera_db_id) / "frame.json"


def _flat_frame_jpeg_path(*, store_db_id: int, camera_id: str) -> Path:
    return EDITOR_FRAMES_ROOT / str(store_db_id) / f"{camera_id}.jpg"


def _flat_frame_meta_path(*, store_db_id: int, camera_id: str) -> Path:
    return EDITOR_FRAMES_ROOT / str(store_db_id) / f"{camera_id}.json"


def _legacy_data_frame_jpeg_path(*, store_db_id: int, camera_db_id: int) -> Path:
    return LEGACY_DATA_FRAMES_ROOT / str(store_db_id) / str(camera_db_id) / "frame.jpg"


def _legacy_data_frame_meta_path(*, store_db_id: int, camera_db_id: int) -> Path:
    return LEGACY_DATA_FRAMES_ROOT / str(store_db_id) / str(camera_db_id) / "frame.json"


def _copy_frame_with_meta(
    *,
    source_jpeg: Path,
    jpeg_target: Path,
    meta_target: Path,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
    source_meta_paths: list[Path],
) -> None:
    jpeg_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_jpeg, jpeg_target)

    legacy_meta: dict[str, Any] | None = None
    for meta_path in source_meta_paths:
        if not meta_path.exists():
            continue
        with meta_path.open(encoding="utf-8") as handle:
            legacy_meta = json.load(handle)
        break

    meta = legacy_meta or {}
    meta.setdefault("store_db_id", store_db_id)
    meta.setdefault("camera_db_id", camera_db_id)
    meta["camera_id"] = camera_id
    with meta_target.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)


def _should_copy_legacy_source(source_jpeg: Path, target_jpeg: Path) -> bool:
    if not target_jpeg.exists():
        return True
    source_stat = source_jpeg.stat()
    target_stat = target_jpeg.stat()
    if source_stat.st_mtime > target_stat.st_mtime:
        return True
    return source_stat.st_size > target_stat.st_size


def migrate_legacy_data_editor_frames() -> int:
    """Copia frames de data/editor_frames/ para server/upload/editor_frames/.

    Retorna quantos frames foram migrados. Frames em data/ são legado — o painel
    só persiste em server/upload/ (pasta portável com o deploy do server/).
    """
    if not LEGACY_DATA_FRAMES_ROOT.is_dir():
        return 0

    migrated = 0
    for store_dir in sorted(LEGACY_DATA_FRAMES_ROOT.iterdir()):
        if not store_dir.is_dir():
            continue
        try:
            store_db_id = int(store_dir.name)
        except ValueError:
            continue
        for camera_dir in sorted(store_dir.iterdir()):
            if not camera_dir.is_dir():
                continue
            try:
                camera_db_id = int(camera_dir.name)
            except ValueError:
                continue

            legacy_jpeg = camera_dir / "frame.jpg"
            if not legacy_jpeg.is_file():
                continue

            jpeg_target = editor_frame_jpeg_path(
                store_db_id=store_db_id, camera_db_id=camera_db_id
            )
            if not _should_copy_legacy_source(legacy_jpeg, jpeg_target):
                continue

            meta_target = editor_frame_meta_path(
                store_db_id=store_db_id, camera_db_id=camera_db_id
            )
            camera_id = str(camera_db_id)
            legacy_meta = camera_dir / "frame.json"
            if legacy_meta.is_file():
                with legacy_meta.open(encoding="utf-8") as handle:
                    meta_payload = json.load(handle)
                camera_id = str(meta_payload.get("camera_id") or camera_id)

            _copy_frame_with_meta(
                source_jpeg=legacy_jpeg,
                jpeg_target=jpeg_target,
                meta_target=meta_target,
                store_db_id=store_db_id,
                camera_db_id=camera_db_id,
                camera_id=camera_id,
                source_meta_paths=[legacy_meta],
            )
            migrated += 1
    return migrated


def ensure_editor_frame_migrated(
    *,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
) -> bool:
    """Garante frame em upload/editor_frames/{loja}/{camera_db_id}/frame.jpg."""
    jpeg_target = editor_frame_jpeg_path(
        store_db_id=store_db_id, camera_db_id=camera_db_id
    )
    if jpeg_target.exists():
        legacy_jpeg = _legacy_data_frame_jpeg_path(
            store_db_id=store_db_id, camera_db_id=camera_db_id
        )
        if legacy_jpeg.is_file() and _should_copy_legacy_source(legacy_jpeg, jpeg_target):
            meta_target = editor_frame_meta_path(
                store_db_id=store_db_id, camera_db_id=camera_db_id
            )
            _copy_frame_with_meta(
                source_jpeg=legacy_jpeg,
                jpeg_target=jpeg_target,
                meta_target=meta_target,
                store_db_id=store_db_id,
                camera_db_id=camera_db_id,
                camera_id=camera_id,
                source_meta_paths=[
                    _legacy_data_frame_meta_path(
                        store_db_id=store_db_id, camera_db_id=camera_db_id
                    )
                ],
            )
        return True

    meta_target = editor_frame_meta_path(
        store_db_id=store_db_id, camera_db_id=camera_db_id
    )

    flat_jpeg = _flat_frame_jpeg_path(store_db_id=store_db_id, camera_id=camera_id)
    if flat_jpeg.exists():
        _copy_frame_with_meta(
            source_jpeg=flat_jpeg,
            jpeg_target=jpeg_target,
            meta_target=meta_target,
            store_db_id=store_db_id,
            camera_db_id=camera_db_id,
            camera_id=camera_id,
            source_meta_paths=[
                _flat_frame_meta_path(store_db_id=store_db_id, camera_id=camera_id)
            ],
        )
        return True

    legacy_jpeg = _legacy_data_frame_jpeg_path(
        store_db_id=store_db_id, camera_db_id=camera_db_id
    )
    if legacy_jpeg.exists():
        _copy_frame_with_meta(
            source_jpeg=legacy_jpeg,
            jpeg_target=jpeg_target,
            meta_target=meta_target,
            store_db_id=store_db_id,
            camera_db_id=camera_db_id,
            camera_id=camera_id,
            source_meta_paths=[
                _legacy_data_frame_meta_path(
                    store_db_id=store_db_id, camera_db_id=camera_db_id
                )
            ],
        )
        return True

    return False


def editor_frame_exists(
    *,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
) -> bool:
    ensure_editor_frame_migrated(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera_id,
    )
    return editor_frame_jpeg_path(
        store_db_id=store_db_id, camera_db_id=camera_db_id
    ).exists()


def load_editor_frame_meta(
    *,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
) -> dict[str, Any] | None:
    ensure_editor_frame_migrated(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera_id,
    )
    path = editor_frame_meta_path(store_db_id=store_db_id, camera_db_id=camera_db_id)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_editor_frame(
    *,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
    jpeg: bytes,
    width: int,
    height: int,
    source: str,
    video_date: str | None = None,
    seconds: float | None = None,
    video_relpath: str | None = None,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    frame_dir = editor_frame_dir(store_db_id=store_db_id, camera_db_id=camera_db_id)
    frame_dir.mkdir(parents=True, exist_ok=True)

    jpeg_path = editor_frame_jpeg_path(store_db_id=store_db_id, camera_db_id=camera_db_id)
    meta_path = editor_frame_meta_path(store_db_id=store_db_id, camera_db_id=camera_db_id)

    jpeg_path.write_bytes(jpeg)
    meta = {
        "store_db_id": store_db_id,
        "camera_db_id": camera_db_id,
        "camera_id": camera_id,
        "width": width,
        "height": height,
        "source": source,
        "video_date": video_date,
        "seconds": seconds,
        "video_relpath": video_relpath,
        "duration_sec": duration_sec,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    return meta


def editor_frame_url(*, store_db_id: int, camera_db_id: int) -> str:
    return f"/stores/{store_db_id}/cameras/{camera_db_id}/editor-frame"
