from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from track_fraude.alerts import build_alerts_index, evaluate_r1_session

R1_MIN_DURATION_SEC = 60.0
from track_fraude.events import (
    build_checkout_sessions_for_track,
    build_store_timeline_for_track,
    build_timelines_document,
)
from track_fraude.pos import FilePosClient
from track_fraude.pos_match import enrich_timelines_with_pos
from track_fraude.storage.paths import ProcessedScope
from track_fraude.zones import CameraZones, ZonePolygon, ZonesConfig

ROOT = Path(__file__).resolve().parents[1]

PORTAL_POLYGON = [[50, 200], [350, 200], [350, 650], [50, 650]]

DEMO_CHECKOUT_LANES = (
    (1, [[80, 300], [380, 300], [380, 650], [80, 650]]),
    (2, [[450, 300], [750, 300], [750, 650], [450, 650]]),
    (3, [[820, 300], [1120, 300], [1120, 650], [820, 650]]),
)


def _demo_zones_config() -> ZonesConfig:
    return ZonesConfig(
        store_id="LOJA-01",
        group_code="default",
        hysteresis_sec=3.0,
        cameras={
            "cam1": CameraZones(
                camera_id="cam1",
                portal=ZonePolygon(
                    zone_id="portal",
                    label="Porta (entrada e saída)",
                    polygon=PORTAL_POLYGON,
                    entry_vector=[0.0, 1.0],
                ),
            ),
            "cam2": CameraZones(
                camera_id="cam2",
                checkout_lanes=[
                    ZonePolygon(
                        zone_id=f"checkout_lane_{lane_id}",
                        lane_id=lane_id,
                        label=f"Caixa {lane_id}",
                        polygon=polygon,
                    )
                    for lane_id, polygon in DEMO_CHECKOUT_LANES
                ],
            ),
        },
    )


def _bbox_in_lane(lane_id: int, *, offset: float = 0.0) -> tuple[float, float, float, float]:
    lane_centers = {
        1: 230.0,
        2: 600.0,
        3: 970.0,
    }
    cx = lane_centers[lane_id] + offset
    return (cx - 40, 400.0, cx + 40, 580.0)


def _track_rows_in_lane(
    *,
    track_id: int,
    lane_id: int,
    t_start: datetime,
    duration_sec: int,
    step_sec: int = 5,
) -> list[dict]:
    rows = []
    x1, y1, x2, y2 = _bbox_in_lane(lane_id)
    elapsed = 0
    while elapsed <= duration_sec:
        t = t_start + timedelta(seconds=elapsed)
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": elapsed,
                "t_abs": t.isoformat(),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
        )
        elapsed += step_sec
    return rows


@pytest.fixture
def zones_config() -> ZonesConfig:
    return _demo_zones_config()


@pytest.fixture
def pos_root_lane2_only(tmp_path: Path) -> Path:
    pos_dir = tmp_path / "pos" / "2026-05-22"
    pos_dir.mkdir(parents=True)
    payload = {
        "store_id": "LOJA-01",
        "date": "2026-05-22",
        "timezone": "America/Sao_Paulo",
        "transactions": [
            {
                "transaction_id": "TX-L2",
                "t_sale": "2026-05-22T06:12:00",
                "lane_id": 2,
                "status": "paid",
                "items": [{"sku": "B", "name": "Item", "qty": 1, "unit_price": 5.0}],
                "qty_total": 1,
                "total_value": 5.0,
            },
        ],
    }
    (pos_dir / "transactions.json").write_text(
        __import__("json").dumps(payload, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "pos"


@pytest.fixture
def pos_root_with_lane3_sale(tmp_path: Path) -> Path:
    pos_dir = tmp_path / "pos" / "2026-05-22"
    pos_dir.mkdir(parents=True)
    payload = {
        "store_id": "LOJA-01",
        "date": "2026-05-22",
        "timezone": "America/Sao_Paulo",
        "transactions": [
            {
                "transaction_id": "TX-L3",
                "t_sale": "2026-05-22T06:12:00",
                "lane_id": 3,
                "status": "paid",
                "items": [{"sku": "A", "name": "Item", "qty": 1, "unit_price": 10.0}],
                "qty_total": 1,
                "total_value": 10.0,
            },
            {
                "transaction_id": "TX-L2",
                "t_sale": "2026-05-22T06:12:00",
                "lane_id": 2,
                "status": "paid",
                "items": [{"sku": "B", "name": "Item", "qty": 1, "unit_price": 5.0}],
                "qty_total": 1,
                "total_value": 5.0,
            },
        ],
    }
    (pos_dir / "transactions.json").write_text(
        __import__("json").dumps(payload, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "pos"


def test_timelines_path():
    scope = ProcessedScope.from_config(
        "data/processed",
        {"group_code": "default", "store_id": "LOJA-01"},
    )
    assert scope.timelines_path("2026-05-22") == Path(
        "data/processed/default/LOJA-01/2026-05-22/events/timelines.json"
    )
    assert scope.alerts_index_path("2026-05-22") == Path(
        "data/processed/default/LOJA-01/2026-05-22/alerts/index.json"
    )


def test_fsm_hysteresis_requires_3_seconds(zones_config: ZonesConfig):
    camera_zones = zones_config.camera("cam2")
    t0 = datetime(2026, 5, 22, 6, 10, 0)
    short_rows = _track_rows_in_lane(
        track_id=1,
        lane_id=3,
        t_start=t0,
        duration_sec=2,
        step_sec=1,
    )
    sessions = build_checkout_sessions_for_track(
        short_rows,
        camera_zones,
        hysteresis_sec=3.0,
    )
    assert sessions == []


def test_r1_no_sale_after_5_minutes(zones_config: ZonesConfig, pos_root_lane2_only: Path):
    t0 = datetime(2026, 5, 22, 6, 10, 0)
    rows = _track_rows_in_lane(
        track_id=10,
        lane_id=3,
        t_start=t0,
        duration_sec=300,
        step_sec=5,
    )
    timelines = build_timelines_document(
        zones=zones_config,
        camera_id="cam2",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=rows,
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root_lane2_only),
        delta_sec=60,
    )
    session = enriched["tracks"][0]["checkout_sessions"][0]
    assert session["duration_sec"] >= 290
    assert session["pos_matches"] == []

    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        min_duration_sec=R1_MIN_DURATION_SEC,
    )
    assert index["alert_count"] == 1
    assert index["alerts"][0]["rule_id"] == "R1"
    assert index["alerts"][0]["checkout_session"]["lane_id"] == 3


def test_r1_suppressed_when_sale_in_interval(
    zones_config: ZonesConfig, pos_root_with_lane3_sale: Path
):
    t0 = datetime(2026, 5, 22, 6, 10, 0)
    rows = _track_rows_in_lane(
        track_id=11,
        lane_id=3,
        t_start=t0,
        duration_sec=300,
        step_sec=5,
    )
    timelines = build_timelines_document(
        zones=zones_config,
        camera_id="cam2",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=rows,
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root_with_lane3_sale),
        delta_sec=60,
    )
    session = enriched["tracks"][0]["checkout_sessions"][0]
    assert len(session["pos_matches"]) == 1
    assert not evaluate_r1_session(session, min_duration_sec=R1_MIN_DURATION_SEC)

    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        min_duration_sec=R1_MIN_DURATION_SEC,
    )
    assert index["alert_count"] == 0


def test_r1_independent_per_lane(
    zones_config: ZonesConfig, pos_root_lane2_only: Path
):
    t0 = datetime(2026, 5, 22, 6, 10, 0)
    rows_lane3 = _track_rows_in_lane(
        track_id=20,
        lane_id=3,
        t_start=t0,
        duration_sec=300,
        step_sec=5,
    )
    rows_lane2 = _track_rows_in_lane(
        track_id=21,
        lane_id=2,
        t_start=t0,
        duration_sec=300,
        step_sec=5,
    )
    timelines = build_timelines_document(
        zones=zones_config,
        camera_id="cam2",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=rows_lane3 + rows_lane2,
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root_lane2_only),
        delta_sec=60,
    )

    sessions_by_lane = {
        session["lane_id"]: session
        for track in enriched["tracks"]
        for session in track["checkout_sessions"]
    }
    assert len(sessions_by_lane[3]["pos_matches"]) == 0
    assert len(sessions_by_lane[2]["pos_matches"]) == 1

    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        min_duration_sec=R1_MIN_DURATION_SEC,
    )
    assert index["alert_count"] == 1
    assert index["alerts"][0]["checkout_session"]["lane_id"] == 3


def test_multiple_checkout_sessions(zones_config: ZonesConfig):
    camera_zones = zones_config.camera("cam2")
    t0 = datetime(2026, 5, 22, 6, 0, 0)
    first_visit = _track_rows_in_lane(
        track_id=5,
        lane_id=3,
        t_start=t0,
        duration_sec=120,
        step_sec=5,
    )
    outside_start = t0 + timedelta(seconds=125)
    outside_rows = []
    for elapsed in range(0, 10, 1):
        t = outside_start + timedelta(seconds=elapsed)
        outside_rows.append(
            {
                "track_id": 5,
                "frame_idx": 100 + elapsed,
                "t_abs": t.isoformat(),
                "x1": 10.0,
                "y1": 400.0,
                "x2": 50.0,
                "y2": 580.0,
            }
        )
    gap_start = outside_start + timedelta(seconds=15)
    second_visit = _track_rows_in_lane(
        track_id=5,
        lane_id=3,
        t_start=gap_start,
        duration_sec=120,
        step_sec=5,
    )
    sessions = build_checkout_sessions_for_track(
        first_visit + outside_rows + second_visit,
        camera_zones,
        hysteresis_sec=3.0,
    )
    assert len(sessions) == 2


def _track_rows_at_foot(
    *,
    track_id: int,
    foot_x: float,
    foot_y: float,
    t_start: datetime,
    duration_sec: int,
    step_sec: int = 1,
    drift: tuple[float, float] = (0.0, 0.0),
) -> list[dict]:
    rows = []
    elapsed = 0
    while elapsed <= duration_sec:
        fx = foot_x + drift[0] * elapsed
        fy = foot_y + drift[1] * elapsed
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": elapsed,
                "t_abs": (t_start + timedelta(seconds=elapsed)).isoformat(),
                "x1": fx - 40,
                "y1": fy - 180,
                "x2": fx + 40,
                "y2": fy,
            }
        )
        elapsed += step_sec
    return rows


def test_portal_alternating_enter_and_leave():
    portal = ZonePolygon(
        zone_id="portal",
        label="Porta",
        polygon=PORTAL_POLYGON,
    )
    camera_zones = CameraZones(camera_id="cam1", portal=portal)
    t0 = datetime(2026, 5, 22, 8, 0, 0)

    enter_rows = _track_rows_at_foot(
        track_id=1,
        foot_x=150,
        foot_y=500,
        t_start=t0,
        duration_sec=5,
        drift=(0.0, 10.0),
    )
    outside_rows = _track_rows_at_foot(
        track_id=1,
        foot_x=15,
        foot_y=500,
        t_start=t0 + timedelta(seconds=10),
        duration_sec=5,
    )
    leave_rows = _track_rows_at_foot(
        track_id=1,
        foot_x=150,
        foot_y=620,
        t_start=t0 + timedelta(seconds=20),
        duration_sec=5,
        drift=(0.0, -10.0),
    )

    timeline = build_store_timeline_for_track(
        enter_rows + outside_rows + leave_rows,
        camera_zones,
        hysteresis_sec=3.0,
    )
    events = [item["event"] for item in timeline]
    assert events == ["entered", "left"]


def test_portal_direction_with_entry_vector():
    portal = ZonePolygon(
        zone_id="portal",
        label="Porta",
        polygon=PORTAL_POLYGON,
        entry_vector=[0.0, 1.0],
    )
    camera_zones = CameraZones(camera_id="cam1", portal=portal)
    t0 = datetime(2026, 5, 22, 8, 0, 0)

    enter_rows = _track_rows_at_foot(
        track_id=2,
        foot_x=150,
        foot_y=480,
        t_start=t0,
        duration_sec=5,
        drift=(0.0, 15.0),
    )
    outside_rows = _track_rows_at_foot(
        track_id=2,
        foot_x=15,
        foot_y=500,
        t_start=t0 + timedelta(seconds=10),
        duration_sec=5,
    )
    leave_rows = _track_rows_at_foot(
        track_id=2,
        foot_x=150,
        foot_y=620,
        t_start=t0 + timedelta(seconds=20),
        duration_sec=5,
        drift=(0.0, -15.0),
    )

    timeline = build_store_timeline_for_track(
        enter_rows + outside_rows + leave_rows,
        camera_zones,
        hysteresis_sec=3.0,
    )
    events = [item["event"] for item in timeline]
    assert events == ["entered", "left"]
    assert all(item.get("mode") == "portal" for item in timeline)


def test_same_entrance_exit_polygon_uses_portal_mode():
    polygon = PORTAL_POLYGON
    camera_zones = CameraZones.from_dict(
        "cam1",
        {
            "entrance": {
                "zone_id": "door",
                "polygon": polygon,
            },
            "exit": {
                "zone_id": "door",
                "polygon": polygon,
            },
        },
    )
    assert camera_zones.portal is not None

    t0 = datetime(2026, 5, 22, 8, 0, 0)
    enter_rows = _track_rows_at_foot(
        track_id=3,
        foot_x=150,
        foot_y=500,
        t_start=t0,
        duration_sec=5,
    )
    outside_rows = _track_rows_at_foot(
        track_id=3,
        foot_x=15,
        foot_y=500,
        t_start=t0 + timedelta(seconds=10),
        duration_sec=5,
    )
    leave_rows = _track_rows_at_foot(
        track_id=3,
        foot_x=150,
        foot_y=550,
        t_start=t0 + timedelta(seconds=20),
        duration_sec=5,
    )
    timeline = build_store_timeline_for_track(
        enter_rows + outside_rows + leave_rows,
        camera_zones,
        hysteresis_sec=3.0,
    )
    assert [item["event"] for item in timeline] == ["entered", "left"]
