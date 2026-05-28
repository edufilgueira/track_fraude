from __future__ import annotations

from track_fraude.vision.carry import compute_carry_profile, _merge_yolo_into_snapshot


def test_merge_yolo_into_snapshot_combines_counts():
    snap = {
        "hands_empty": True,
        "hand_objects_bbox": 0,
        "hand_objects": 0,
        "carry_score": 0.1,
        "bag": False,
    }
    merged = _merge_yolo_into_snapshot(snap, {"count": 1, "labels": ["bottle"]})
    assert merged is not None
    assert merged["hand_objects_yolo"] == 1
    assert merged["hand_objects"] == 1
    assert merged["hands_empty"] is False
    assert merged["yolo_labels"] == ["bottle"]


def test_compute_carry_profile_with_yolo_payload():
    timeline = [
        {"event": "entered", "t": "2026-05-22T10:00:00"},
        {"event": "left", "t": "2026-05-22T10:05:00"},
    ]
    rows = [
        {
            "track_id": 1,
            "t_abs": "2026-05-22T10:00:00",
            "x1": 100,
            "y1": 100,
            "x2": 140,
            "y2": 200,
        },
        {
            "track_id": 1,
            "t_abs": "2026-05-22T10:04:58",
            "x1": 100,
            "y1": 100,
            "x2": 180,
            "y2": 200,
        },
    ]
    profile = compute_carry_profile(
        store_timeline=timeline,
        track_rows=rows,
        yolo_at_enter={"count": 0, "labels": []},
        yolo_at_exit={"count": 0, "labels": []},
    )
    assert profile is not None
    assert profile.source == "bbox+yolo"
    assert profile.carry_delta()["positive"] is False
