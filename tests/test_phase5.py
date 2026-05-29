from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from track_fraude.evidence import (
    EvidenceWindow,
    build_evidence_pack,
    build_summary_text,
    compute_checkout_range,
    compute_evidence_range,
)
from track_fraude.storage import ProcessedScope, processed_root


def _sample_alert() -> dict:
    return {
        "alert_id": "AL-20260522-0001",
        "rule_id": "R1",
        "severity": "high",
        "date": "2026-05-22",
        "track_key": "cam2:T5",
        "global_person_id": "P-0004",
        "checkout_session": {
            "session_id": "S1",
            "lane_id": 1,
            "t_start": "2026-05-22T10:00:36.154615",
            "t_end": "2026-05-22T10:01:01.312896",
            "duration_sec": 25.158,
        },
        "pos_matches": [],
        "store_timeline": [
            {
                "event": "left",
                "t": "2026-05-22T10:01:03.812063",
                "zone_id": "portal",
            }
        ],
        "summary": "Permaneceu no caixa 1 por 25s sem venda registrada",
    }


def test_compute_evidence_range_applies_buffers():
    window = EvidenceWindow(buffer_before_sec=20.0, buffer_after_sec=20.0)
    t_start, t_end = compute_evidence_range(_sample_alert(), window=window)
    assert t_start == datetime.fromisoformat("2026-05-22T10:00:16.154615")
    assert t_end == datetime.fromisoformat("2026-05-22T10:01:23.812063")


def test_compute_checkout_range_is_narrower():
    window = EvidenceWindow(
        checkout_buffer_before_sec=5.0,
        checkout_buffer_after_sec=5.0,
    )
    checkout = compute_checkout_range(_sample_alert(), window=window)
    assert checkout is not None
    t_start, t_end = checkout
    assert t_start == datetime.fromisoformat("2026-05-22T10:00:31.154615")
    assert t_end == datetime.fromisoformat("2026-05-22T10:01:06.312896")


def test_summary_includes_pos_and_videos():
    text = build_summary_text(_sample_alert())
    assert "P-0004" in text
    assert "POS: Nenhuma venda" in text
    assert "cam1_clip.mp4" in text
    assert "cam2_checkout_clip.mp4" in text


def test_build_evidence_pack_without_clips(tmp_path: Path):
    project_root = tmp_path
    config = {
        "store_id": "LOJA-01",
        "group_code": "default",
        "cameras": {
            "cam1": {"camera_role": "entrance"},
            "cam2": {"camera_role": "checkout"},
        },
    }
    processed = ProcessedScope.from_config(processed_root(project_root), config)

    with patch("track_fraude.evidence.builder.extract_clip_for_range"):
        pack = build_evidence_pack(
            alert=_sample_alert(),
            date="2026-05-22",
            project_root=project_root,
            processed=processed,
            config=config,
            window=EvidenceWindow(),
            skip_clips=True,
        )

    expected_dir = (
        project_root
        / "data/processed/default/LOJA-01/2026-05-22/review/AL-20260522-0001"
    )
    assert pack.output_dir == expected_dir
    assert (pack.output_dir / "timeline.json").is_file()
    assert (pack.output_dir / "pos_context.json").is_file()
    assert (pack.output_dir / "summary.txt").is_file()
    assert (pack.output_dir / "evidence.json").is_file()
