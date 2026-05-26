from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from track_fraude.zones.geometry import foot_point, point_in_polygon
from track_fraude.zones.models import CameraZones, ZonePolygon


def _parse_t_abs(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _lane_for_point(
    x: float,
    y: float,
    lanes: list[ZonePolygon],
) -> ZonePolygon | None:
    matches = [
        lane for lane in lanes if point_in_polygon(x, y, lane.polygon)
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return min(matches, key=lambda lane: lane.lane_id or 0)


@dataclass
class _LanePresenceState:
    status: str = "outside"
    pending_since: datetime | None = None
    t_start: datetime | None = None


@dataclass
class CheckoutSession:
    session_id: str
    lane_id: int
    zone_id: str
    t_start: datetime
    t_end: datetime | None = None

    @property
    def duration_sec(self) -> float | None:
        if self.t_end is None:
            return None
        return (self.t_end - self.t_start).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "lane_id": self.lane_id,
            "zone_id": self.zone_id,
            "t_start": self.t_start.isoformat(),
        }
        if self.t_end is not None:
            payload["t_end"] = self.t_end.isoformat()
            payload["duration_sec"] = round(self.duration_sec or 0.0, 3)
        return payload


@dataclass
class CheckoutLaneFSM:
    """FSM por track + lane com histerese temporal (~3 s)."""

    hysteresis_sec: float = 3.0
    lane_states: dict[int, _LanePresenceState] = field(default_factory=dict)
    sessions: list[CheckoutSession] = field(default_factory=list)
    _session_counter: int = 0

    def _state_for_lane(self, lane_id: int) -> _LanePresenceState:
        if lane_id not in self.lane_states:
            self.lane_states[lane_id] = _LanePresenceState()
        return self.lane_states[lane_id]

    def _open_session(self, lane: ZonePolygon, t: datetime) -> None:
        self._session_counter += 1
        self.sessions.append(
            CheckoutSession(
                session_id=f"S{self._session_counter}",
                lane_id=int(lane.lane_id or 0),
                zone_id=lane.zone_id,
                t_start=t,
            )
        )

    def _close_session(self, lane_id: int, t: datetime) -> None:
        for session in reversed(self.sessions):
            if session.lane_id == lane_id and session.t_end is None:
                session.t_end = t
                return

    def update(self, lane: ZonePolygon | None, t: datetime) -> None:
        if lane is None:
            for lane_id, state in list(self.lane_states.items()):
                if state.status in {"inside", "pending_enter", "pending_exit"}:
                    self._apply_outside(lane_id, t, state)
            return

        lane_id = int(lane.lane_id or 0)
        state = self._state_for_lane(lane_id)
        self._apply_inside(lane, t, state)

        for other_lane_id, other_state in list(self.lane_states.items()):
            if other_lane_id == lane_id:
                continue
            if other_state.status in {"inside", "pending_enter"}:
                self._apply_outside(other_lane_id, t, other_state)

    def _apply_inside(
        self,
        lane: ZonePolygon,
        t: datetime,
        state: _LanePresenceState,
    ) -> None:
        lane_id = int(lane.lane_id or 0)
        if state.status == "outside":
            state.status = "pending_enter"
            state.pending_since = t
            return

        if state.status == "pending_enter":
            assert state.pending_since is not None
            if (t - state.pending_since).total_seconds() >= self.hysteresis_sec:
                state.status = "inside"
                state.t_start = state.pending_since
                state.pending_since = None
                self._open_session(lane, state.t_start)
            return

        if state.status == "pending_exit":
            state.status = "inside"
            state.pending_since = None

    def _apply_outside(
        self,
        lane_id: int,
        t: datetime,
        state: _LanePresenceState,
    ) -> None:
        if state.status == "outside":
            return

        if state.status == "pending_enter":
            state.status = "outside"
            state.pending_since = None
            return

        if state.status == "inside":
            state.status = "pending_exit"
            state.pending_since = t
            return

        if state.status == "pending_exit":
            assert state.pending_since is not None
            if (t - state.pending_since).total_seconds() >= self.hysteresis_sec:
                self._close_session(lane_id, state.pending_since)
                state.status = "outside"
                state.pending_since = None
                state.t_start = None

    def finalize(self, t: datetime) -> None:
        for lane_id, state in list(self.lane_states.items()):
            if state.status == "inside":
                self._close_session(lane_id, t)
                state.status = "outside"
                state.t_start = None
                state.pending_since = None
            elif state.status == "pending_enter":
                state.status = "outside"
                state.pending_since = None
            elif state.status == "pending_exit":
                self._close_session(lane_id, t)
                state.status = "outside"
                state.pending_since = None
                state.t_start = None


@dataclass
class StoreZoneFSM:
    """FSM cam1: eventos entered / left com histerese."""

    hysteresis_sec: float = 3.0
    entrance_status: str = "outside"
    exit_status: str = "outside"
    entrance_pending_since: datetime | None = None
    exit_pending_since: datetime | None = None
    entered_at: datetime | None = None
    left_at: datetime | None = None
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def update(
        self,
        entrance: ZonePolygon | None,
        exit_zone: ZonePolygon | None,
        x: float,
        y: float,
        t: datetime,
    ) -> None:
        if entrance is not None:
            inside_entrance = point_in_polygon(x, y, entrance.polygon)
            self._update_entrance(inside_entrance, t)

        if exit_zone is not None:
            inside_exit = point_in_polygon(x, y, exit_zone.polygon)
            self._update_exit(inside_exit, t)

    def _update_entrance(self, inside: bool, t: datetime) -> None:
        if inside:
            if self.entrance_status == "outside":
                self.entrance_status = "pending"
                self.entrance_pending_since = t
            elif self.entrance_status == "pending":
                assert self.entrance_pending_since is not None
                if (t - self.entrance_pending_since).total_seconds() >= self.hysteresis_sec:
                    self.entrance_status = "inside"
                    self.entered_at = self.entrance_pending_since
                    self.timeline.append({"event": "entered", "t": self.entered_at.isoformat()})
                    self.entrance_pending_since = None
        elif self.entrance_status == "pending":
            self.entrance_status = "outside"
            self.entrance_pending_since = None

    def _update_exit(self, inside: bool, t: datetime) -> None:
        if inside:
            if self.exit_status == "outside":
                self.exit_status = "pending"
                self.exit_pending_since = t
            elif self.exit_status == "pending":
                assert self.exit_pending_since is not None
                if (t - self.exit_pending_since).total_seconds() >= self.hysteresis_sec:
                    self.exit_status = "inside"
                    self.left_at = self.exit_pending_since
                    self.timeline.append({"event": "left", "t": self.left_at.isoformat()})
                    self.exit_pending_since = None
        elif self.exit_status == "pending":
            self.exit_status = "outside"
            self.exit_pending_since = None

    def finalize(self, t: datetime) -> None:
        if self.entrance_status == "pending":
            self.entrance_status = "outside"
            self.entrance_pending_since = None
        if self.exit_status == "pending":
            self.exit_status = "outside"
            self.exit_pending_since = None


def _motion_vector(points: list[tuple[float, float]]) -> tuple[float, float]:
    if len(points) < 2:
        return (0.0, 0.0)
    x0, y0 = points[0]
    x1, y1 = points[-1]
    return (x1 - x0, y1 - y0)


def _classify_portal_crossing(
    motion: tuple[float, float],
    *,
    entry_vector: list[float] | None,
    next_event: str,
    min_motion_px: float = 8.0,
) -> str:
    if entry_vector is None:
        return next_event

    mx, my = motion
    motion_len = (mx * mx + my * my) ** 0.5
    if motion_len < min_motion_px:
        return next_event

    dot = mx * entry_vector[0] + my * entry_vector[1]
    if dot > 0:
        return "entered"
    if dot < 0:
        return "left"
    return next_event


@dataclass
class PortalFSM:
    """Porta única: alterna entered/left a cada passagem ou usa vetor de movimento."""

    portal: ZonePolygon
    hysteresis_sec: float = 3.0
    status: str = "outside"
    pending_since: datetime | None = None
    next_event: str = "entered"
    approach_points: list[tuple[float, float]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def update(self, x: float, y: float, t: datetime) -> None:
        inside = point_in_polygon(x, y, self.portal.polygon)
        if inside:
            self._apply_inside(x, y, t)
        else:
            self._apply_outside(t)

    def _apply_inside(self, x: float, y: float, t: datetime) -> None:
        if self.status == "outside":
            self.status = "pending_enter"
            self.pending_since = t
            self.approach_points = [(x, y)]
            return

        if self.status == "pending_enter":
            self.approach_points.append((x, y))
            assert self.pending_since is not None
            if (t - self.pending_since).total_seconds() >= self.hysteresis_sec:
                event = _classify_portal_crossing(
                    _motion_vector(self.approach_points),
                    entry_vector=self.portal.entry_vector,
                    next_event=self.next_event,
                )
                self.timeline.append(
                    {
                        "event": event,
                        "t": self.pending_since.isoformat(),
                        "zone_id": self.portal.zone_id,
                        "mode": "portal",
                    }
                )
                self.next_event = "left" if event == "entered" else "entered"
                self.status = "inside"
                self.pending_since = None
                self.approach_points.clear()
            return

        if self.status == "pending_exit":
            self.status = "inside"
            self.pending_since = None

    def _apply_outside(self, t: datetime) -> None:
        if self.status == "outside":
            return

        if self.status == "pending_enter":
            self.status = "outside"
            self.pending_since = None
            self.approach_points.clear()
            return

        if self.status == "inside":
            self.status = "pending_exit"
            self.pending_since = t
            return

        if self.status == "pending_exit":
            assert self.pending_since is not None
            if (t - self.pending_since).total_seconds() >= self.hysteresis_sec:
                self.status = "outside"
                self.pending_since = None

    def finalize(self, t: datetime) -> None:
        if self.status == "pending_enter":
            self.status = "outside"
            self.pending_since = None
            self.approach_points.clear()
        elif self.status == "pending_exit":
            self.status = "outside"
            self.pending_since = None


def build_checkout_sessions_for_track(
    rows: list[dict[str, Any]],
    camera_zones: CameraZones,
    *,
    hysteresis_sec: float = 3.0,
) -> list[dict[str, Any]]:
    if not camera_zones.checkout_lanes:
        return []

    sorted_rows = sorted(rows, key=lambda row: _parse_t_abs(row["t_abs"]))
    fsm = CheckoutLaneFSM(hysteresis_sec=hysteresis_sec)

    for row in sorted_rows:
        fx, fy = foot_point(row["x1"], row["y1"], row["x2"], row["y2"])
        lane = _lane_for_point(fx, fy, camera_zones.checkout_lanes)
        t = _parse_t_abs(row["t_abs"])
        fsm.update(lane, t)

    if sorted_rows:
        last_t = _parse_t_abs(sorted_rows[-1]["t_abs"])
        fsm.finalize(last_t)

    return [session.to_dict() for session in fsm.sessions if session.t_end is not None]


def build_store_timeline_for_track(
    rows: list[dict[str, Any]],
    camera_zones: CameraZones,
    *,
    hysteresis_sec: float = 3.0,
) -> list[dict[str, Any]]:
    if camera_zones.portal is not None:
        sorted_rows = sorted(rows, key=lambda row: _parse_t_abs(row["t_abs"]))
        fsm = PortalFSM(portal=camera_zones.portal, hysteresis_sec=hysteresis_sec)
        for row in sorted_rows:
            fx, fy = foot_point(row["x1"], row["y1"], row["x2"], row["y2"])
            t = _parse_t_abs(row["t_abs"])
            fsm.update(fx, fy, t)
        if sorted_rows:
            fsm.finalize(_parse_t_abs(sorted_rows[-1]["t_abs"]))
        return fsm.timeline

    if camera_zones.entrance is None and camera_zones.exit is None:
        return []

    sorted_rows = sorted(rows, key=lambda row: _parse_t_abs(row["t_abs"]))
    fsm = StoreZoneFSM(hysteresis_sec=hysteresis_sec)

    for row in sorted_rows:
        fx, fy = foot_point(row["x1"], row["y1"], row["x2"], row["y2"])
        t = _parse_t_abs(row["t_abs"])
        fsm.update(camera_zones.entrance, camera_zones.exit, fx, fy, t)

    if sorted_rows:
        fsm.finalize(_parse_t_abs(sorted_rows[-1]["t_abs"]))

    return fsm.timeline
