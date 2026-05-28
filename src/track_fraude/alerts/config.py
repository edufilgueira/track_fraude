from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRuleConfig:
    """Parâmetros das regras R1–R5 (Fase 6)."""

    min_checkout_duration_sec: float = 60.0
    t_return_sec: float = 1800.0  # 30 min — R1b
    carry_area_ratio_threshold: float = 1.25
    carry_confidence_threshold: float = 0.55
    net_carry_score_threshold: float = 0.15
    exit_snapshot_start_before_sec: float = 10.0
    exit_snapshot_end_before_sec: float = 2.0
    r3_visual_margin: int = 2
    r4_min_items: int = 5
    r4_fast_duration_sec: float = 90.0
    require_left_store: bool = True
    enable_r4: bool = True
    r5_cancelled_delta_sec: int = 60

    rule_weights: tuple[tuple[str, float], ...] = (
        ("R1", 40.0),
        ("R2", 40.0),
        ("R5", 35.0),
        ("R3", 25.0),
        ("R4", 15.0),
    )

    @classmethod
    def from_min_duration(cls, min_duration_sec: float) -> AlertRuleConfig:
        return cls(min_checkout_duration_sec=min_duration_sec)
