from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from track_fraude.alerts import build_alerts_index
from track_fraude.events import build_timelines_document
from track_fraude.merge import (
    apply_persons_to_timelines,
    build_persons_document,
    build_track_profiles,
    match_entrance_to_checkout,
)
from track_fraude.pos import FilePosClient
from track_fraude.pos_match import enrich_timelines_with_pos
from track_fraude.zones import CameraZones, ZonePolygon, ZonesConfig

R1_MIN_DURATION_SEC = 60.0

PORTAL_POLYGON = [[50, 200], [350, 200], [350, 650], [50, 650]]
CHECKOUT_LANE_1 = [[80, 300], [380, 300], [380, 650], [80, 650]]


def _zones_config() -> ZonesConfig:
    return ZonesConfig(
        store_id="LOJA-01",
        group_code="default",
        hysteresis_sec=3.0,
        cameras={
            "cam1": CameraZones(
                camera_id="cam1",
                portal=ZonePolygon(
                    zone_id="portal",
                    label="Porta",
                    polygon=PORTAL_POLYGON,
                    entry_vector=[0.0, 1.0],
                ),
            ),
            "cam2": CameraZones(
                camera_id="cam2",
                checkout_lanes=[
                    ZonePolygon(
                        zone_id="checkout_lane_1",
                        lane_id=1,
                        label="Caixa 1",
                        polygon=CHECKOUT_LANE_1,
                    )
                ],
            ),
        },
    )


def _portal_rows(track_id: int, t_start: datetime, *, steps: int = 8) -> list[dict]:
    rows = []
    for step in range(steps):
        t = t_start + timedelta(seconds=step)
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": step,
                "t_abs": t.isoformat(),
                "x1": 120.0,
                "y1": 300.0,
                "x2": 180.0,
                "y2": 580.0,
            }
        )
    return rows


def _checkout_rows(track_id: int, t_start: datetime, *, duration_sec: int = 300) -> list[dict]:
    rows = []
    for elapsed in range(0, duration_sec + 1, 5):
        t = t_start + timedelta(seconds=elapsed)
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": elapsed,
                "t_abs": t.isoformat(),
                "x1": 180.0,
                "y1": 400.0,
                "x2": 260.0,
                "y2": 580.0,
            }
        )
    return rows


def test_match_two_people_without_swap():
    t0 = datetime(2026, 5, 22, 10, 0, 0)
    entrance = build_track_profiles(
        _portal_rows(1, t0) + _portal_rows(2, t0 + timedelta(seconds=120)),
        camera_id="cam1",
    )
    checkout = build_track_profiles(
        _checkout_rows(10, t0 + timedelta(seconds=60))
        + _checkout_rows(11, t0 + timedelta(seconds=240)),
        camera_id="cam2",
    )

    links = match_entrance_to_checkout(entrance, checkout, max_travel_sec=600)
    assert len(links) == 2
    assert links[0].entrance_track.track_id == 1
    assert links[0].checkout_track.track_id == 10
    assert links[1].entrance_track.track_id == 2
    assert links[1].checkout_track.track_id == 11


def test_same_person_gets_single_global_person_id():
    t0 = datetime(2026, 5, 22, 10, 0, 0)
    persons_doc, links_doc = build_persons_document(
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        entrance_camera="cam1",
        checkout_camera="cam2",
        entrance_rows=_portal_rows(3, t0),
        checkout_rows=_checkout_rows(5, t0 + timedelta(seconds=90), duration_sec=300),
        max_travel_sec=1800,
    )

    assert persons_doc["person_count"] == 1
    assert persons_doc["cross_camera_link_count"] == 1
    assert links_doc["link_count"] == 1
    assert persons_doc["persons"][0]["global_person_id"] == "P-0001"
    track_keys = {track["track_key"] for track in persons_doc["persons"][0]["tracks"]}
    assert track_keys == {"cam1:T3", "cam2:T5"}


def test_r1_alert_includes_global_person_id_and_store_timeline(
    tmp_path: Path,
):
    zones = _zones_config()
    t0 = datetime(2026, 5, 22, 10, 0, 0)
    cam1_rows = _portal_rows(3, t0, steps=12)
    cam2_rows = _checkout_rows(5, t0 + timedelta(seconds=90), duration_sec=300)

    cam1_timelines = build_timelines_document(
        zones=zones,
        camera_id="cam1",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=cam1_rows,
    )
    timelines = build_timelines_document(
        zones=zones,
        camera_id="cam2",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=cam2_rows,
        existing=cam1_timelines,
    )

    persons_doc, _links = build_persons_document(
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        entrance_camera="cam1",
        checkout_camera="cam2",
        entrance_rows=cam1_rows,
        checkout_rows=cam2_rows,
        timelines=timelines,
        max_travel_sec=1800,
    )
    timelines = apply_persons_to_timelines(timelines, persons_doc)

    pos_root = tmp_path / "pos"
    pos_dir = pos_root / "2026-05-22"
    pos_dir.mkdir(parents=True)
    (pos_dir / "transactions.json").write_text(
        '{"store_id":"LOJA-01","date":"2026-05-22","timezone":"America/Sao_Paulo","transactions":[]}',
        encoding="utf-8",
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )

    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        min_duration_sec=R1_MIN_DURATION_SEC,
    )
    assert index["alert_count"] == 1
    alert = index["alerts"][0]
    assert alert["global_person_id"] == "P-0001"
    assert alert["store_timeline"]
    assert alert["store_timeline"][0]["event"] == "entered"
