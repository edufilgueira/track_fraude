from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from track_fraude.models.sync import SyncMap
from track_fraude.yolo_device import resolve_yolo_device


def _log_yolo_device(device: object, *, phase: str) -> None:
    """Log inequívoco do device usado (GPU vs CPU) para diagnóstico de lentidão."""
    cuda_available = False
    gpu_name = "n/a"
    torch_version = "n/a"
    try:
        import torch

        torch_version = torch.__version__
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            gpu_name = torch.cuda.get_device_name(0)
    except Exception as exc:  # noqa: BLE001
        gpu_name = f"erro torch: {exc}"
    print(
        f"[{phase}] device={device!r} cuda_available={cuda_available} "
        f"gpu={gpu_name} torch={torch_version}",
        flush=True,
    )


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
    _log_yolo_device(device, phase="track")
    model = YOLO(cfg.model_name)
    try:
        print(f"[track] modelo carregado em device={getattr(model, 'device', 'n/a')}", flush=True)
    except Exception:  # noqa: BLE001
        pass

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

    inference_started = time.perf_counter()
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

    inference_elapsed = time.perf_counter() - inference_started
    ms_per_frame = (inference_elapsed * 1000.0 / processed_frames) if processed_frames else 0.0
    print(
        f"[track] frames processados={processed_frames} "
        f"(frame_count={sync_map.frame_count}, vid_stride={vid_stride}) "
        f"em {inference_elapsed:.1f}s = {ms_per_frame:.1f} ms/frame",
        flush=True,
    )

    stats = {
        "detection_count": len(rows),
        "unique_tracks": len(track_ids),
        "frames_with_detections": frames_with_detections,
        "processed_frames": processed_frames,
        "inference_elapsed_sec": round(inference_elapsed, 2),
        "ms_per_frame": round(ms_per_frame, 2),
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
