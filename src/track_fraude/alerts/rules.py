from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def session_duration_sec(session: dict[str, Any]) -> float:
    if "duration_sec" in session:
        return float(session["duration_sec"])
    t_start = _parse_dt(session["t_start"])
    t_end = _parse_dt(session["t_end"])
    return (t_end - t_start).total_seconds()


def evaluate_r1_session(
    session: dict[str, Any],
    *,
    min_duration_sec: float,
) -> bool:
    if session.get("t_end") is None:
        return False
    duration = session_duration_sec(session)
    if duration <= min_duration_sec:
        return False
    pos_matches = session.get("pos_matches")
    if pos_matches is None:
        return False
    return len(pos_matches) == 0


def build_r1_alert(
    *,
    alert_index: int,
    date: str,
    track: dict[str, Any],
    session: dict[str, Any],
    store_timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    alert_id = f"AL-{date.replace('-', '')}-{alert_index:04d}"
    payload: dict[str, Any] = {
        "alert_id": alert_id,
        "rule_id": "R1",
        "severity": "high",
        "date": date,
        "track_key": track.get("track_key"),
        "track_id": track.get("track_id"),
        "camera_id": track.get("camera_id"),
        "checkout_session": {
            "session_id": session.get("session_id"),
            "lane_id": session.get("lane_id"),
            "zone_id": session.get("zone_id"),
            "t_start": session.get("t_start"),
            "t_end": session.get("t_end"),
            "duration_sec": session.get("duration_sec"),
        },
        "pos_matches": session.get("pos_matches", []),
        "summary": (
            f"Permaneceu no caixa {session.get('lane_id')} "
            f"por {session.get('duration_sec', 0):.0f}s sem venda registrada"
        ),
    }
    global_person_id = track.get("global_person_id")
    if global_person_id:
        payload["global_person_id"] = global_person_id
    if store_timeline:
        payload["store_timeline"] = store_timeline
    return payload


def _store_timeline_for_track(
    timelines: dict[str, Any], track: dict[str, Any]
) -> list[dict[str, Any]]:
    global_person_id = track.get("global_person_id")
    if not global_person_id:
        return []
    entrance_camera = timelines.get("persons_ref", {}).get("entrance_camera", "cam1")
    for other in timelines.get("tracks", []):
        if other.get("global_person_id") != global_person_id:
            continue
        if other.get("camera_id") == entrance_camera:
            return list(other.get("timeline", []))
    return []


def evaluate_r1_alerts(
    timelines: dict[str, Any],
    *,
    date: str,
    min_duration_sec: float,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    alert_index = 1
    seen_person_session: set[tuple[str, str]] = set()

    for track in timelines.get("tracks", []):
        for session in track.get("checkout_sessions", []):
            if not evaluate_r1_session(session, min_duration_sec=min_duration_sec):
                continue
            global_person_id = track.get("global_person_id")
            session_id = str(session.get("session_id", ""))
            if global_person_id:
                dedupe_key = (str(global_person_id), session_id)
                if dedupe_key in seen_person_session:
                    continue
                seen_person_session.add(dedupe_key)
            alerts.append(
                build_r1_alert(
                    alert_index=alert_index,
                    date=date,
                    track=track,
                    session=session,
                    store_timeline=_store_timeline_for_track(timelines, track),
                )
            )
            alert_index += 1

    return alerts


def build_alerts_index(
    timelines: dict[str, Any],
    *,
    date: str,
    store_id: str,
    group_code: str,
    min_duration_sec: float,
) -> dict[str, Any]:
    alerts = evaluate_r1_alerts(
        timelines,
        date=date,
        min_duration_sec=min_duration_sec,
    )
    return {
        "date": date,
        "store_id": store_id,
        "group_code": group_code,
        "rules": ["R1"],
        "min_checkout_duration_sec": min_duration_sec,
        "alert_count": len(alerts),
        "alerts": alerts,
    }
