from __future__ import annotations

from track_fraude.evidence.store_config import (
    evidence_encode_settings_from_store,
    evidence_window_from_store,
)


def test_evidence_window_from_store_defaults():
    window = evidence_window_from_store({})
    assert window.buffer_before_sec == 20.0
    assert window.buffer_after_sec == 20.0
    assert window.checkout_buffer_before_sec == 5.0
    assert window.checkout_buffer_after_sec == 5.0
    assert window.max_duration_sec == 300.0


def test_evidence_window_from_store_config_block():
    config = {
        "evidence": {
            "buffer_before_sec": 30,
            "buffer_after_sec": 25,
            "checkout_buffer_before_sec": 8,
            "checkout_buffer_after_sec": 7,
        }
    }
    window = evidence_window_from_store(config, max_duration_sec=120.0)
    assert window.buffer_before_sec == 30.0
    assert window.buffer_after_sec == 25.0
    assert window.checkout_buffer_before_sec == 8.0
    assert window.checkout_buffer_after_sec == 7.0
    assert window.max_duration_sec == 120.0


def test_evidence_encode_settings_from_store_defaults():
    settings = evidence_encode_settings_from_store({})
    assert settings.scale_width is None
    assert settings.preset == "fast"
    assert settings.crf == 28


def test_evidence_encode_settings_from_store_config_block():
    config = {
        "evidence": {
            "scale_width": 1280,
            "ffmpeg_preset": "faster",
            "crf": 30,
        }
    }
    settings = evidence_encode_settings_from_store(config)
    assert settings.scale_width == 1280
    assert settings.preset == "faster"
    assert settings.crf == 30
