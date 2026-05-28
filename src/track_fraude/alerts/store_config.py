from __future__ import annotations

from typing import Any

from track_fraude.alerts.config import AlertRuleConfig


def alert_rule_config_from_store(
    config_store: dict[str, Any],
    *,
    require_left_store: bool = True,
) -> AlertRuleConfig:
    sync = config_store.get("sync") or {}
    rules = config_store.get("alert_rules") or {}
    return AlertRuleConfig(
        min_checkout_duration_sec=float(sync.get("r1_min_checkout_duration_sec", 20)),
        t_return_sec=float(rules.get("t_return_sec", 1800)),
        carry_confidence_threshold=float(rules.get("carry_confidence_threshold", 0.55)),
        r3_visual_margin=int(rules.get("r3_visual_margin", 2)),
        r4_min_items=int(rules.get("r4_min_items", 5)),
        r4_fast_duration_sec=float(rules.get("r4_fast_duration_sec", 90)),
        enable_r4=bool(rules.get("enable_r4", True)),
        r5_cancelled_delta_sec=int(rules.get("r5_cancelled_delta_sec", 60)),
        require_left_store=require_left_store,
    )
