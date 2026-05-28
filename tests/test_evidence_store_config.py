from __future__ import annotations

from track_fraude.evidence.store_config import evidence_window_from_store


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
