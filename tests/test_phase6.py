from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from track_fraude.alerts import (
    AlertRuleConfig,
    build_alerts_index,
    is_r1_suppressed_by_r1b,
)
from track_fraude.events import build_timelines_document
from track_fraude.pos import FilePosClient
from track_fraude.pos_match import enrich_timelines_with_pos
from track_fraude.zones import CameraZones, ZonePolygon, ZonesConfig

R1_MIN = 60.0
PORTAL = [[50, 200], [350, 200], [350, 650], [50, 650]]
LANE_1 = [[80, 300], [380, 300], [380, 650], [80, 650]]


def _zones() -> ZonesConfig:
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
                    polygon=PORTAL,
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
                        polygon=LANE_1,
                    )
                ],
            ),
        },
    )


def _portal_visit_rows(track_id: int, t0: datetime) -> list[dict]:
    rows = []
    for step in range(10):
        t = t0 + timedelta(seconds=step)
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
    for step in range(40, 50):
        t = t0 + timedelta(seconds=step)
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": step,
                "t_abs": t.isoformat(),
                "x1": 15.0,
                "y1": 300.0,
                "x2": 55.0,
                "y2": 580.0,
            }
        )
    return rows


def _lane_rows(
    track_id: int,
    t0: datetime,
    *,
    duration_sec: int = 120,
    step_sec: int = 5,
) -> list[dict]:
    rows = []
    elapsed = 0
    while elapsed <= duration_sec:
        t = t0 + timedelta(seconds=elapsed)
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
        elapsed += step_sec
    return rows


def _outside_lane_rows(track_id: int, t0: datetime, *, seconds: int = 15) -> list[dict]:
    rows = []
    for elapsed in range(0, seconds + 1):
        t = t0 + timedelta(seconds=elapsed)
        rows.append(
            {
                "track_id": track_id,
                "frame_idx": elapsed,
                "t_abs": t.isoformat(),
                "x1": 10.0,
                "y1": 400.0,
                "x2": 50.0,
                "y2": 580.0,
            }
        )
    return rows


def _carry_preset(*, confidence: float = 0.8, net_theft: bool = True) -> dict:
    if net_theft:
        return {
            "carry_at_enter": {
                "hands_empty": True,
                "hand_objects": 0,
                "bag": False,
                "carry_score": 0.1,
                "bbox_area": 10000.0,
            },
            "carry_at_exit": {
                "hands_empty": False,
                "hand_objects": 1,
                "bag": False,
                "carry_score": 0.75,
                "bbox_area": 12000.0,
            },
            "confidence": confidence,
            "source": "test",
        }
    return {
        "carry_at_enter": {
            "hands_empty": True,
            "hand_objects": 0,
            "bag": False,
            "carry_score": 0.1,
            "bbox_area": 10000.0,
        },
        "carry_at_exit": {
            "hands_empty": True,
            "hand_objects": 0,
            "bag": False,
            "carry_score": 0.12,
            "bbox_area": 10100.0,
        },
        "confidence": confidence,
        "source": "test",
    }


def _write_pos(tmp_path: Path, transactions: list[dict]) -> Path:
    pos_dir = tmp_path / "pos" / "2026-05-22"
    pos_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "store_id": "LOJA-01",
        "date": "2026-05-22",
        "timezone": "America/Sao_Paulo",
        "transactions": transactions,
    }
    (pos_dir / "transactions.json").write_text(
        __import__("json").dumps(payload, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "pos"


def _merge_timelines(cam1_rows: list[dict], cam2_rows: list[dict]) -> dict:
    zones = _zones()
    doc = build_timelines_document(
        zones=zones,
        camera_id="cam1",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=cam1_rows,
    )
    return build_timelines_document(
        zones=zones,
        camera_id="cam2",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=cam2_rows,
        existing=doc,
    )


def _apply_person(timelines: dict, person_id: str = "P-0001") -> dict:
    for track in timelines["tracks"]:
        track["global_person_id"] = person_id
    timelines["persons_ref"] = {"entrance_camera": "cam1"}
    return timelines


def test_r1b_suppresses_first_session_when_later_paid(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 10, 0, 0)
    cam2 = (
        _lane_rows(5, t0, duration_sec=120)
        + _outside_lane_rows(5, t0 + timedelta(seconds=130), seconds=20)
        + _lane_rows(5, t0 + timedelta(seconds=160), duration_sec=90)
    )
    timelines = _merge_timelines(_portal_visit_rows(1, t0), cam2)
    timelines = _apply_person(timelines)

    pos_root = _write_pos(
        tmp_path,
        [
            {
                "transaction_id": "TX-2",
                "t_sale": "2026-05-22T10:04:00",
                "lane_id": 1,
                "status": "paid",
                "items": [{"sku": "A", "name": "Item", "qty": 1, "unit_price": 5.0}],
                "qty_total": 1,
                "total_value": 5.0,
            }
        ],
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    sessions = enriched["tracks"][1]["checkout_sessions"]
    assert len(sessions) == 2
    assert sessions[0]["pos_matches"] == []
    assert sessions[1]["pos_matches"]

    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, t_return_sec=1800.0)
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    r1 = [alert for alert in index["alerts"] if alert["rule_id"] == "R1"]
    assert r1 == []


def test_r1b_unit():
    first = {
        "session_id": "S1",
        "lane_id": 1,
        "t_start": "2026-05-22T10:00:00",
        "t_end": "2026-05-22T10:02:00",
        "pos_matches": [],
    }
    second = {
        "session_id": "S2",
        "lane_id": 1,
        "t_start": "2026-05-22T10:05:00",
        "t_end": "2026-05-22T10:07:00",
        "pos_matches": [{"transaction_id": "TX", "status": "paid", "qty_total": 1}],
    }
    assert is_r1_suppressed_by_r1b(first, [first, second], t_return_sec=1800.0)


def test_r2_skip_checkout_with_carry_delta(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 11, 0, 0)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), [])
    timelines = _apply_person(timelines)
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = _carry_preset()

    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, require_left_store=True)
    index = build_alerts_index(
        timelines,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(_write_pos(tmp_path, [])),
    )
    r2 = [a for a in index["alerts"] if a["rule_id"] == "R2"]
    assert len(r2) == 1
    assert r2[0]["suspicion_score"] >= 28.0


def test_r1_only_when_checkout_without_r2(tmp_path: Path):
    """Passou no caixa sem pagar → R1; R2 não (skip checkout exigido)."""
    t0 = datetime(2026, 5, 22, 10, 0, 0)
    cam2 = _lane_rows(5, t0, duration_sec=120)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), cam2)
    timelines = _apply_person(timelines)
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = _carry_preset(net_theft=True)

    pos_root = _write_pos(tmp_path, [])
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, require_left_store=True)
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    assert index["alert_count"] == 1
    alert = index["alerts"][0]
    assert alert["rule_id"] == "R1"
    assert "R2" not in (alert.get("rule_ids") or [])


def test_r2_suppressed_when_went_to_checkout(tmp_path: Path):
    """Caso tipo P-0004: passou no caixa → sem R2 mesmo com delta visual."""
    t0 = datetime(2026, 5, 22, 10, 1, 14)
    cam2 = (
        _lane_rows(9, t0 + timedelta(seconds=10), duration_sec=14, step_sec=5)
        + _outside_lane_rows(9, t0 + timedelta(seconds=28), seconds=4)
        + _lane_rows(9, t0 + timedelta(seconds=33), duration_sec=14, step_sec=5)
    )
    timelines = _merge_timelines(_portal_visit_rows(9, t0), cam2)
    timelines = _apply_person(timelines, person_id="P-0004")
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = _carry_preset(net_theft=True)

    pos_root = _write_pos(tmp_path, [])
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, require_left_store=True)
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    r2 = [a for a in index["alerts"] if a["rule_id"] == "R2" or "R2" in (a.get("rule_ids") or [])]
    assert r2 == []


def test_net_carry_empty_to_empty_no_r2(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 11, 0, 0)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), [])
    timelines = _apply_person(timelines)
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = _carry_preset(net_theft=False)

    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, require_left_store=True)
    index = build_alerts_index(
        timelines,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(_write_pos(tmp_path, [])),
    )
    assert index["alert_count"] == 0


def test_r3_qty_mismatch(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 12, 0, 0)
    cam2 = _lane_rows(5, t0, duration_sec=180)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), cam2)
    timelines = _apply_person(timelines)
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = {
                "carry_at_enter": {"bag": False, "hand_objects": 0, "bbox_area": 10000.0},
                "carry_at_exit": {"bag": True, "hand_objects": 4, "bbox_area": 20000.0},
                "confidence": 0.75,
                "source": "test",
            }

    pos_root = _write_pos(
        tmp_path,
        [
            {
                "transaction_id": "TX-R3",
                "t_sale": "2026-05-22T12:01:30",
                "lane_id": 1,
                "status": "paid",
                "items": [{"sku": "A", "name": "Item", "qty": 1, "unit_price": 3.0}],
                "qty_total": 1,
                "total_value": 3.0,
            }
        ],
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, r3_visual_margin=2)
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    r3 = [a for a in index["alerts"] if a["rule_id"] == "R3"]
    assert len(r3) == 1


def test_r4_fast_checkout_many_items(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 13, 0, 0)
    cam2 = _lane_rows(5, t0, duration_sec=45, step_sec=5)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), cam2)
    timelines = _apply_person(timelines)

    pos_root = _write_pos(
        tmp_path,
        [
            {
                "transaction_id": "TX-R4",
                "t_sale": "2026-05-22T13:00:30",
                "lane_id": 1,
                "status": "paid",
                "items": [{"sku": "X", "name": "Pack", "qty": 8, "unit_price": 2.0}],
                "qty_total": 8,
                "total_value": 16.0,
            }
        ],
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    config = AlertRuleConfig(
        min_checkout_duration_sec=R1_MIN,
        r4_min_items=5,
        r4_fast_duration_sec=90.0,
        enable_r4=True,
    )
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    r4 = [a for a in index["alerts"] if a["rule_id"] == "R4"]
    assert len(r4) == 1


def test_r5_cancelled_with_carry(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 14, 0, 0)
    cam2 = _lane_rows(5, t0, duration_sec=120)
    timelines = _merge_timelines(_portal_visit_rows(1, t0), cam2)
    timelines = _apply_person(timelines)
    for track in timelines["tracks"]:
        if track["camera_id"] == "cam1":
            track["vision_signals"] = _carry_preset()

    pos_root = _write_pos(
        tmp_path,
        [
            {
                "transaction_id": "TX-CAN",
                "t_sale": "2026-05-22T14:01:00",
                "lane_id": 1,
                "status": "cancelled",
                "items": [{"sku": "Z", "name": "Item", "qty": 2, "unit_price": 4.0}],
                "qty_total": 2,
                "total_value": 8.0,
            }
        ],
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id="LOJA-01",
        date="2026-05-22",
        pos_client=FilePosClient(pos_root),
        delta_sec=60,
    )
    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN)
    index = build_alerts_index(
        enriched,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(pos_root),
    )
    r5 = [a for a in index["alerts"] if a["rule_id"] == "R5"]
    assert len(r5) == 1
    assert r5[0]["cancelled_transactions"]


def test_r2_not_emitted_without_left_event(tmp_path: Path):
    t0 = datetime(2026, 5, 22, 15, 0, 0)
    rows = []
    for step in range(10):
        t = t0 + timedelta(seconds=step)
        rows.append(
            {
                "track_id": 1,
                "frame_idx": step,
                "t_abs": t.isoformat(),
                "x1": 120.0,
                "y1": 300.0,
                "x2": 180.0,
                "y2": 580.0,
            }
        )
    zones = _zones()
    timelines = build_timelines_document(
        zones=zones,
        camera_id="cam1",
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        track_rows=rows,
    )
    for track in timelines["tracks"]:
        track["vision_signals"] = _carry_preset()
    config = AlertRuleConfig(min_checkout_duration_sec=R1_MIN, require_left_store=True)
    index = build_alerts_index(
        timelines,
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        config=config,
        pos_client=FilePosClient(_write_pos(tmp_path, [])),
    )
    assert not [a for a in index["alerts"] if a["rule_id"] == "R2"]
