from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from track_fraude.vision.carry import CarryProfile, compute_carry_profile


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


@dataclass
class PersonVisit:
    global_person_id: str | None
    track_key: str
    cam1_track: dict[str, Any] | None = None
    cam2_tracks: list[dict[str, Any]] = field(default_factory=list)
    store_timeline: list[dict[str, Any]] = field(default_factory=list)
    checkout_sessions: list[dict[str, Any]] = field(default_factory=list)
    carry_profile: CarryProfile | None = None
    primary_checkout_track: dict[str, Any] | None = None

    @property
    def has_left_store(self) -> bool:
        return any(event.get("event") == "left" for event in self.store_timeline)

    @property
    def has_entered_store(self) -> bool:
        return any(event.get("event") == "entered" for event in self.store_timeline)

    @property
    def visit_start(self) -> datetime | None:
        entered = next(
            (event for event in self.store_timeline if event.get("event") == "entered"),
            None,
        )
        if entered and entered.get("t"):
            return _parse_dt(entered["t"])
        if self.checkout_sessions:
            return min(_parse_dt(s["t_start"]) for s in self.checkout_sessions)
        return None

    @property
    def visit_end(self) -> datetime | None:
        left = next(
            (event for event in self.store_timeline if event.get("event") == "left"),
            None,
        )
        if left and left.get("t"):
            return _parse_dt(left["t"])
        if self.checkout_sessions:
            return max(_parse_dt(s["t_end"]) for s in self.checkout_sessions if s.get("t_end"))
        return None

    def paid_pos_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for session in self.checkout_sessions:
            for match in session.get("pos_matches") or []:
                if str(match.get("status", "paid")) in {"paid", "completed"}:
                    matches.append(match)
        return matches

    def paid_qty_total(self) -> int:
        return sum(int(match.get("qty_total", 0)) for match in self.paid_pos_matches())

    def ready_for_visit_rules(self, *, require_left_store: bool) -> bool:
        if not self.store_timeline:
            return True
        if require_left_store:
            return self.has_left_store
        return True

    def attach_carry_profile(
        self,
        *,
        track_rows: list[dict[str, Any]] | None = None,
        area_ratio_threshold: float = 1.25,
    ) -> None:
        preset = None
        if self.cam1_track:
            preset = self.cam1_track.get("vision_signals")
        self.carry_profile = compute_carry_profile(
            store_timeline=self.store_timeline,
            track_rows=track_rows,
            preset=preset,
            area_ratio_threshold=area_ratio_threshold,
        )


def _entrance_camera(timelines: dict[str, Any]) -> str:
    return str(timelines.get("persons_ref", {}).get("entrance_camera", "cam1"))


def build_person_visits(
    timelines: dict[str, Any],
    *,
    track_rows_by_key: dict[str, list[dict[str, Any]]] | None = None,
    area_ratio_threshold: float = 1.25,
) -> list[PersonVisit]:
    entrance_camera = _entrance_camera(timelines)
    grouped: dict[str, PersonVisit] = {}

    for track in timelines.get("tracks", []):
        person_id = track.get("global_person_id")
        key = str(person_id) if person_id else str(track.get("track_key"))
        if key not in grouped:
            grouped[key] = PersonVisit(
                global_person_id=str(person_id) if person_id else None,
                track_key=str(track.get("track_key")),
            )
        visit = grouped[key]
        camera_id = track.get("camera_id")
        if camera_id == entrance_camera:
            visit.cam1_track = track
            visit.store_timeline = list(track.get("timeline") or [])
        if track.get("checkout_sessions"):
            visit.cam2_tracks.append(track)
            visit.checkout_sessions.extend(track.get("checkout_sessions") or [])
            visit.primary_checkout_track = track

    visits = list(grouped.values())
    for visit in visits:
        rows = None
        if track_rows_by_key and visit.cam1_track:
            rows = track_rows_by_key.get(str(visit.cam1_track.get("track_key")))
        visit.attach_carry_profile(
            track_rows=rows,
            area_ratio_threshold=area_ratio_threshold,
        )
    return visits
