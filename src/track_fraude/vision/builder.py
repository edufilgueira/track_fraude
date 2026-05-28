from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from track_fraude.models.sync import SyncMap
from track_fraude.vision.carry import (
    bbox_area,
    compute_carry_profile,
    rows_before_time,
    rows_near_time,
    _parse_dt,
)
from track_fraude.vision.frame_extract import read_frame_at_timestamp
from track_fraude.vision.object_carry import detect_carry_objects


def _person_bbox_near_rows(rows: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    if not rows:
        return None
    x1 = sum(float(row["x1"]) for row in rows) / len(rows)
    y1 = sum(float(row["y1"]) for row in rows) / len(rows)
    x2 = sum(float(row["x2"]) for row in rows) / len(rows)
    y2 = sum(float(row["y2"]) for row in rows) / len(rows)
    return x1, y1, x2, y2


def _mean_bbox_area(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(bbox_area(row) for row in rows) / len(rows)


def _yolo_detection_for_moment(
    *,
    video_path: Path,
    sync_map: SyncMap,
    target: datetime,
    track_rows: list[dict[str, Any]],
    model_name: str,
    conf: float,
) -> dict[str, Any] | None:
    rows = rows_near_time(track_rows, target, window_sec=2.0)
    if _mean_bbox_area(rows) <= 0:
        rows = rows_near_time(track_rows, target, window_sec=5.0)
    person_bbox = _person_bbox_near_rows(rows)
    try:
        frame, frame_idx = read_frame_at_timestamp(video_path, sync_map, target)
    except (FileNotFoundError, RuntimeError):
        return None
    detection = detect_carry_objects(
        frame,
        person_bbox=person_bbox,
        model_name=model_name,
        conf=conf,
    )
    payload = detection.to_dict()
    payload["frame_idx"] = frame_idx
    return payload


def enrich_track_vision_signals(
    *,
    track: dict[str, Any],
    track_rows: list[dict[str, Any]] | None,
    video_path: Path | None = None,
    sync_map: SyncMap | None = None,
    model_name: str = "yolov8n.pt",
    conf: float = 0.35,
    use_yolo: bool = True,
) -> dict[str, Any] | None:
    timeline = track.get("timeline") or []
    yolo_enter = None
    yolo_exit = None

    can_run_yolo = (
        use_yolo
        and track_rows
        and video_path is not None
        and video_path.is_file()
        and sync_map is not None
    )
    if can_run_yolo:
        entered = next((event for event in timeline if event.get("event") == "entered"), None)
        left = next((event for event in timeline if event.get("event") == "left"), None)
        if entered and entered.get("t"):
            yolo_enter = _yolo_detection_for_moment(
                video_path=video_path,
                sync_map=sync_map,
                target=_parse_dt(entered["t"]),
                track_rows=track_rows,
                model_name=model_name,
                conf=conf,
            )
        if left and left.get("t"):
            exit_rows = rows_before_time(track_rows, _parse_dt(left["t"]))
            exit_target = _parse_dt(left["t"])
            if exit_rows:
                mid = exit_rows[len(exit_rows) // 2]
                exit_target = _parse_dt(mid["t_abs"])
            yolo_exit = _yolo_detection_for_moment(
                video_path=video_path,
                sync_map=sync_map,
                target=exit_target,
                track_rows=track_rows,
                model_name=model_name,
                conf=conf,
            )

    profile = compute_carry_profile(
        store_timeline=timeline,
        track_rows=track_rows,
        yolo_at_enter=yolo_enter,
        yolo_at_exit=yolo_exit,
    )
    if profile is None:
        return None
    return profile.to_dict()
