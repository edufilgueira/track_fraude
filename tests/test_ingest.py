from __future__ import annotations

import json
from pathlib import Path

import pytest

from track_fraude.ingest import save_ingest_report, validate_day_ingest


def test_validate_day_ingest_ok_with_default_videos(tmp_path: Path):
    date = "2026-05-22"
    raw_dir = tmp_path / "data" / "raw" / "default" / "LOJA-01" / date
    raw_dir.mkdir(parents=True)
    (raw_dir / "cam1.mp4").write_bytes(b"fake")
    (raw_dir / "cam2.mp4").write_bytes(b"fake")

    pos_root = tmp_path / "data" / "pos"
    pos_root.mkdir(parents=True)
    (pos_root / "transactions.json").write_text(
        json.dumps(
            {
                "store_id": "LOJA-01",
                "date": date,
                "timezone": "America/Sao_Paulo",
                "transactions": [],
            }
        ),
        encoding="utf-8",
    )

    report = validate_day_ingest(
        project_root=tmp_path,
        date=date,
        store_id="LOJA-01",
        group_code="default",
        camera_ids=["cam1", "cam2"],
        pos_root=pos_root,
    )
    assert report.ok is True
    assert "cam1" in report.cameras
    assert report.pos["transaction_count"] == 0
    assert any(item.code == "pos_empty" for item in report.issues)


def test_validate_day_ingest_missing_video_is_error(tmp_path: Path):
    date = "2026-05-22"
    raw_dir = tmp_path / "data" / "raw" / "default" / "LOJA-01" / date
    raw_dir.mkdir(parents=True)

    report = validate_day_ingest(
        project_root=tmp_path,
        date=date,
        store_id="LOJA-01",
        group_code="default",
        camera_ids=["cam1"],
        pos_root=tmp_path / "data" / "pos",
    )
    assert report.ok is False
    assert any(item.code == "video_missing" for item in report.issues)


def test_save_ingest_report(tmp_path: Path):
    from track_fraude.ingest.validator import IngestReport

    report = IngestReport(
        date="2026-05-22",
        store_id="LOJA-01",
        group_code="default",
        raw_day_dir="/tmp/raw",
    )
    path = tmp_path / "ingest_report.json"
    save_ingest_report(path, report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["store_id"] == "LOJA-01"
    assert payload["ok"] is True
