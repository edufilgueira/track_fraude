from __future__ import annotations

from track_fraude.alerts.store_config import alert_rule_config_from_store


def test_alert_rule_config_from_store():
    config = alert_rule_config_from_store(
        {
            "sync": {
                "r1_min_checkout_duration_sec": 45,
                "pos_match_delta_sec": 25,
            },
            "alert_rules": {
                "t_return_sec": 900,
                "r3_visual_margin": 3,
                "carry_confidence_threshold": 0.6,
                "r4_min_items": 7,
                "r4_fast_duration_sec": 100,
                "enable_r4": False,
                "r5_cancelled_delta_sec": 45,
            },
        }
    )
    assert config.min_checkout_duration_sec == 45
    assert config.t_return_sec == 900
    assert config.r3_visual_margin == 3
    assert config.carry_confidence_threshold == 0.6
    assert config.r4_min_items == 7
    assert config.r4_fast_duration_sec == 100
    assert config.enable_r4 is False
    assert config.r5_cancelled_delta_sec == 45
