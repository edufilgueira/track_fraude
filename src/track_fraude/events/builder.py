from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from track_fraude.events.fsm import (
    build_checkout_sessions_for_track,
    build_store_timeline_for_track,
)
from track_fraude.zones.models import CameraZones, ZonesConfig


def _track_key(camera_id: str, track_id: int | str) -> str:
    return f"{camera_id}:T{track_id}"


def build_camera_timelines(
    *,
    camera_id: str,
    date: str,
    store_id: str,
    group_code: str,
    track_rows: list[dict[str, Any]],
    camera_zones: CameraZones,
    hysteresis_sec: float = 3.0,
) -> list[dict[str, Any]]:
    by_track: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in track_rows:
        by_track[int(row["track_id"])].append(row)

    timelines: list[dict[str, Any]] = []
    for track_id in sorted(by_track):
        rows = by_track[track_id]
        checkout_sessions = build_checkout_sessions_for_track(
            rows,
            camera_zones,
            hysteresis_sec=hysteresis_sec,
        )
        timeline = build_store_timeline_for_track(
            rows,
            camera_zones,
            hysteresis_sec=hysteresis_sec,
        )
        timelines.append(
            {
                "track_key": _track_key(camera_id, track_id),
                "track_id": track_id,
                "camera_id": camera_id,
                "timeline": timeline,
                "checkout_sessions": checkout_sessions,
            }
        )

    return timelines


def merge_timelines_payload(
    existing: dict[str, Any] | None,
    *,
    date: str,
    store_id: str,
    group_code: str,
    camera_id: str,
    new_tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(existing or {})
    payload.update(
        {
            "date": date,
            "store_id": store_id,
            "group_code": group_code,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    tracks = [
        item
        for item in payload.get("tracks", [])
        if item.get("camera_id") != camera_id
    ]
    tracks.extend(new_tracks)
    tracks.sort(key=lambda item: (item.get("camera_id", ""), item.get("track_id", 0)))
    payload["tracks"] = tracks
    return payload


def build_timelines_document(
    *,
    zones: ZonesConfig,
    camera_id: str,
    date: str,
    store_id: str,
    group_code: str,
    track_rows: list[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    camera_zones = zones.camera(camera_id)
    new_tracks = build_camera_timelines(
        camera_id=camera_id,
        date=date,
        store_id=store_id,
        group_code=group_code,
        track_rows=track_rows,
        camera_zones=camera_zones,
        hysteresis_sec=zones.hysteresis_sec,
    )
    return merge_timelines_payload(
        existing,
        date=date,
        store_id=store_id,
        group_code=group_code,
        camera_id=camera_id,
        new_tracks=new_tracks,
    )
