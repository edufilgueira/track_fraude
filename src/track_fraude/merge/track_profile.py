from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def track_key(camera_id: str, track_id: int) -> str:
    return f"{camera_id}:T{track_id}"


@dataclass(frozen=True)
class TrackProfile:
    camera_id: str
    track_id: int
    t_first: datetime
    t_last: datetime
    rows: tuple[dict[str, Any], ...]
    appearance: np.ndarray | None = None
    entered_at: datetime | None = None

    @property
    def track_key(self) -> str:
        return track_key(self.camera_id, self.track_id)

    @property
    def reference_time(self) -> datetime:
        return self.entered_at or self.t_first

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "track_key": self.track_key,
            "t_first": self.t_first.isoformat(),
            "t_last": self.t_last.isoformat(),
        }
        if self.entered_at is not None:
            payload["entered_at"] = self.entered_at.isoformat()
        return payload


def group_rows_by_track(
    rows: list[dict[str, Any]], *, camera_id: str
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["track_id"])].append(row)
    return grouped


def build_track_profiles(
    rows: list[dict[str, Any]],
    *,
    camera_id: str,
    appearances: dict[int, np.ndarray] | None = None,
    entered_at_by_track: dict[int, datetime] | None = None,
) -> list[TrackProfile]:
    grouped = group_rows_by_track(rows, camera_id=camera_id)
    profiles: list[TrackProfile] = []
    for track_id in sorted(grouped):
        track_rows = sorted(grouped[track_id], key=lambda row: parse_dt(row["t_abs"]))
        t_first = parse_dt(track_rows[0]["t_abs"])
        t_last = parse_dt(track_rows[-1]["t_abs"])
        entered_at = None
        if entered_at_by_track and track_id in entered_at_by_track:
            entered_at = entered_at_by_track[track_id]
        appearance = appearances.get(track_id) if appearances else None
        profiles.append(
            TrackProfile(
                camera_id=camera_id,
                track_id=track_id,
                t_first=t_first,
                t_last=t_last,
                rows=tuple(track_rows),
                appearance=appearance,
                entered_at=entered_at,
            )
        )
    return profiles


def entered_at_from_timeline(timeline: list[dict[str, Any]]) -> datetime | None:
    for event in timeline:
        if event.get("event") == "entered":
            return parse_dt(event["t"])
    return None
