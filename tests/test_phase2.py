from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from track_fraude.models.sync import SyncAnchor, SyncMap
from track_fraude.pipeline.state import track_phase_status
from track_fraude.storage import FileTrackRepository, ProcessedScope
from track_fraude.track import TrackRunConfig, build_manifest, group_by_frame
from track_fraude.track.parquet_io import read_tracks_parquet, write_tracks_parquet
from track_fraude.track.tracker import _resolve_frame_idx


def test_tracks_path_is_parquet():
    scope = ProcessedScope.from_config(
        "data/processed",
        {"group_code": "default", "store_id": "LOJA-01"},
    )
    assert scope.tracks_path("2026-05-22", "cam2") == Path(
        "data/processed/default/LOJA-01/2026-05-22/cam2/tracks.parquet"
    )
    assert scope.manifest_path("2026-05-22", "cam2") == Path(
        "data/processed/default/LOJA-01/2026-05-22/cam2/manifest.json"
    )


def test_parquet_roundtrip(tmp_path: Path):
    rows = [
        {
            "track_id": 1,
            "frame_idx": 100,
            "t_abs": "2026-05-22T06:14:22",
            "x1": 10.0,
            "y1": 20.0,
            "x2": 110.0,
            "y2": 220.0,
        },
        {
            "track_id": 2,
            "frame_idx": 105,
            "t_abs": "2026-05-22T06:14:22.2",
            "x1": 200.0,
            "y1": 50.0,
            "x2": 280.0,
            "y2": 300.0,
        },
    ]
    path = tmp_path / "tracks.parquet"
    write_tracks_parquet(path, rows)
    recovered = read_tracks_parquet(path)
    assert len(recovered) == 2
    assert recovered[0]["track_id"] == 1
    assert recovered[1]["x2"] == 280.0


def test_group_by_frame():
    rows = [
        {"track_id": 1, "frame_idx": 10},
        {"track_id": 2, "frame_idx": 10},
        {"track_id": 1, "frame_idx": 20},
    ]
    grouped = group_by_frame(rows)
    assert len(grouped[10]) == 2
    assert len(grouped[20]) == 1


def test_track_phase_status():
    state = {
        "cameras": {
            "cam1": {"track": "completed"},
            "cam2": {"track": "pending"},
        }
    }
    assert track_phase_status(state, ["cam1"]) == "completed"
    assert track_phase_status(state, ["cam1", "cam2"]) == "partial"
    assert track_phase_status(state, ["cam2"]) == "pending"


def test_build_manifest():
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
        frame_count=1000,
        timezone="America/Sao_Paulo",
        anchor=anchor,
    )
    config = TrackRunConfig(vid_stride=5)
    manifest = build_manifest(
        camera_id="cam2",
        date="2026-05-22",
        video_path=Path("data/raw/video/2026-05-22/cam2.mp4"),
        sync_map_path=Path("data/processed/default/LOJA-01/2026-05-22/cam2/sync_map.json"),
        tracks_path=Path("tracks.parquet"),
        config=config,
        stats={"detection_count": 10, "unique_tracks": 3},
        frame_count=sync_map.frame_count,
    )
    assert manifest["camera_id"] == "cam2"
    assert manifest["model"] == "yolov8n.pt"
    assert manifest["vid_stride"] == 5
    assert manifest["unique_tracks"] == 3
    assert "bbox" in manifest["schema"]


def test_file_track_repository(tmp_path: Path):
    scope = ProcessedScope(root=tmp_path, group_code="default", store_id="LOJA-01")
    repo = FileTrackRepository(scope)
    rows = [
        {
            "track_id": 7,
            "frame_idx": 50,
            "t_abs": "2026-05-22T06:11:00",
            "x1": 1.0,
            "y1": 2.0,
            "x2": 3.0,
            "y2": 4.0,
        }
    ]
    path = repo.save_tracks("cam2", "2026-05-22", rows)
    assert path.name == "tracks.parquet"
    loaded = repo.load_tracks("cam2", "2026-05-22")
    assert loaded[0]["track_id"] == 7


def test_resolve_frame_idx_without_result_frame():
    class FakeResult:
        pass

    assert _resolve_frame_idx(FakeResult(), 0, 5) == 0
    assert _resolve_frame_idx(FakeResult(), 3, 5) == 15

    class FakeResultWithFrame:
        frame = 42

    assert _resolve_frame_idx(FakeResultWithFrame(), 99, 5) == 42


def test_run_tracking_requires_ultralytics():
    pytest.importorskip("ultralytics", reason="pip install -e '.[track]'")
    from track_fraude.track.tracker import run_tracking

    anchor = SyncAnchor(
        frame_idx=0,
        t_abs=datetime(2026, 5, 22, 6, 10, 0),
        source="test",
    )
    sync_map = SyncMap(
        camera_id="cam2",
        date="2026-05-22",
        video_path="missing.mp4",
        fps=25.0,
        frame_count=100,
        timezone="America/Sao_Paulo",
        anchor=anchor,
    )
    with pytest.raises((FileNotFoundError, RuntimeError)):
        run_tracking(
            video_path=Path("nonexistent_video.mp4"),
            sync_map=sync_map,
            config=TrackRunConfig(vid_stride=10),
        )
