from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from track_fraude.models.sync import SyncAnchor, SyncMap
from track_fraude.pos import FilePosClient

ROOT = Path(__file__).resolve().parents[1]


def test_pos_load_and_query_lane3():
    client = FilePosClient(ROOT / "data" / "pos")
    export = client.get_day_export("LOJA-01", "2026-05-22")
    assert export.store_id == "LOJA-01"
    assert len(export.transactions) == 3

    t_from = datetime(2026, 5, 22, 6, 10, 0)
    t_to = datetime(2026, 5, 22, 6, 15, 0)
    delta = timedelta(seconds=60)
    matches = client.get_transactions_between(
        store_id="LOJA-01",
        date="2026-05-22",
        t_from=t_from - delta,
        t_to=t_to + delta,
        lane_id=3,
    )
    assert len(matches) == 1
    assert matches[0].transaction_id == "TX-001"
    assert matches[0].qty_total == 1


def test_sync_map_frame_time_roundtrip():
    anchor = SyncAnchor(
        frame_idx=0,
        t_abs=datetime(2026, 5, 22, 6, 10, 0),
        source="test",
    )
    sync_map = SyncMap(
        camera_id="cam2",
        date="2026-05-22",
        video_path="test.mp4",
        fps=25.0,
        frame_count=10500,
        timezone="America/Sao_Paulo",
        anchor=anchor,
    )
    target = datetime(2026, 5, 22, 6, 14, 22)
    frame = sync_map.frame_at_timestamp(target)
    recovered = sync_map.timestamp_at_frame(frame)
    assert abs((recovered - target).total_seconds()) < 0.05
