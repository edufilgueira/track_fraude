from __future__ import annotations

from typing import Any

from track_fraude.evidence.window import EvidenceWindow
from track_fraude_core.db.evidence_ffmpeg import EvidenceEncodeSettings, evidence_encode_settings


def evidence_window_from_store(
    config_store: dict[str, Any],
    *,
    max_duration_sec: float = 300.0,
) -> EvidenceWindow:
    evidence = config_store.get("evidence") or {}
    return EvidenceWindow(
        buffer_before_sec=float(evidence.get("buffer_before_sec", 20)),
        buffer_after_sec=float(evidence.get("buffer_after_sec", 20)),
        max_duration_sec=max_duration_sec,
        checkout_buffer_before_sec=float(evidence.get("checkout_buffer_before_sec", 5)),
        checkout_buffer_after_sec=float(evidence.get("checkout_buffer_after_sec", 5)),
    )


def evidence_encode_settings_from_store(
    config_store: dict[str, Any],
) -> EvidenceEncodeSettings:
    evidence = config_store.get("evidence") or {}
    return evidence_encode_settings(
        scale_width=evidence.get("scale_width"),
        preset=evidence.get("ffmpeg_preset"),
        crf=evidence.get("crf"),
    )
