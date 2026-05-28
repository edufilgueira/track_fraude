from __future__ import annotations

from track_fraude.alerts.config import AlertRuleConfig


def rule_weight(config: AlertRuleConfig, rule_id: str) -> float:
    for rid, weight in config.rule_weights:
        if rid == rule_id:
            return weight
    return 10.0


def compute_suspicion_score(
    rule_id: str,
    *,
    config: AlertRuleConfig,
    confidence: float = 1.0,
) -> float:
    weight = rule_weight(config, rule_id)
    return round(weight * max(0.0, min(1.0, confidence)), 1)


def score_band(score: float) -> str:
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    return "low"
