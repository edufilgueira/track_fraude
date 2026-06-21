from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from track_fraude.models.sync import SyncMap
from track_fraude.yolo_device import resolve_yolo_device


@dataclass(frozen=True)
class TrackRunConfig:
    model_name: str = "/app/models/yolov8n.pt"
    tracker: str = "bytetrack.yaml"
    vid_stride: int = 5
    conf: float = 0.5
    person_class: int = 0


def _require_ultralytics():
    try:
        from ultralytics import YOLO  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'Ultralytics não instalado. Execute: pip install -e ".[track]"'
        ) from exc


def _resolve_frame_idx(result: Any, stream_index: int, vid_stride: int) -> int:
    """Índice do frame no vídeo original (Ultralytics nem sempre expõe result.frame)."""
    frame = getattr(result, "frame", None)
    if frame is not None:
        return int(frame)
    return stream_index * max(1, vid_stride)


def run_tracking(
    *,
    video_path: Path,
    sync_map: SyncMap,
    config: TrackRunConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _require_ultralytics()
    from ultralytics import YOLO

    cfg = config or TrackRunConfig()
    device = resolve_yolo_device()
    model = YOLO(cfg.model_name)

    rows: list[dict[str, Any]] = []
    track_ids: set[int] = set()
    frames_with_detections = 0
    processed_frames = 0

    vid_stride = max(1, cfg.vid_stride)

    stream = model.track(
        source=str(video_path),
        stream=True,
        persist=True,
        vid_stride=vid_stride,
        conf=cfg.conf,
        classes=[cfg.person_class],
        tracker=cfg.tracker,
        device=device,
        verbose=False,
    )

    for stream_index, result in enumerate(stream):
        processed_frames += 1
        frame_idx = _resolve_frame_idx(result, stream_index, vid_stride)

        if result.boxes is None or len(result.boxes) == 0:
            continue

        ids = result.boxes.id
        if ids is None:
            continue

        xyxy = result.boxes.xyxy.cpu().numpy()
        id_list = ids.int().cpu().tolist()
        t_abs = sync_map.timestamp_at_frame(frame_idx)
        frames_with_detections += 1

        for track_id, box in zip(id_list, xyxy, strict=True):
            track_ids.add(int(track_id))
            rows.append(
                {
                    "track_id": int(track_id),
                    "frame_idx": frame_idx,
                    "t_abs": t_abs.isoformat(),
                    "x1": float(box[0]),
                    "y1": float(box[1]),
                    "x2": float(box[2]),
                    "y2": float(box[3]),
                }
            )

    stats = {
        "detection_count": len(rows),
        "unique_tracks": len(track_ids),
        "frames_with_detections": frames_with_detections,
        "processed_frames": processed_frames,
    }
    return rows, stats


def build_manifest(
    *,
    camera_id: str,
    date: str,
    video_path: Path,
    sync_map_path: Path,
    tracks_path: Path,
    config: TrackRunConfig,
    stats: dict[str, Any],
    frame_count: int,
) -> dict[str, Any]:
    return {
        "camera_id": camera_id,
        "date": date,
        "video_path": str(video_path.as_posix()),
        "sync_map_path": str(sync_map_path.as_posix()),
        "tracks_parquet": tracks_path.name,
        "schema": {
            "track_id": "int64",
            "frame_idx": "int64",
            "t_abs": "iso8601 string",
            "bbox": ["x1", "y1", "x2", "y2"],
        },
        "model": config.model_name,
        "tracker": config.tracker,
        "vid_stride": config.vid_stride,
        "conf": config.conf,
        "person_class": config.person_class,
        "frame_count": frame_count,
        **stats,
    }
