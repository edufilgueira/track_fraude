from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


@dataclass(frozen=True)
class EvidenceWindow:
    buffer_before_sec: float = 20.0
    buffer_after_sec: float = 20.0
    max_duration_sec: float = 300.0
    checkout_buffer_before_sec: float = 5.0
    checkout_buffer_after_sec: float = 5.0


def _collect_alert_times(alert: dict[str, Any]) -> list[datetime]:
    times: list[datetime] = []
    session = alert.get("checkout_session") or {}
    for key in ("t_start", "t_end"):
        if session.get(key):
            times.append(_parse_dt(session[key]))
    for event in alert.get("store_timeline") or []:
        if event.get("t"):
            times.append(_parse_dt(event["t"]))
    return times


def compute_evidence_range(
    alert: dict[str, Any],
    *,
    window: EvidenceWindow,
) -> tuple[datetime, datetime]:
    """Intervalo absoluto do clip completo (entrada → saída + buffers, cap 5 min)."""
    times = _collect_alert_times(alert)
    if not times:
        raise ValueError(f"Alerta {alert.get('alert_id')} sem timestamps para evidência")

    t_start = min(times) - timedelta(seconds=window.buffer_before_sec)
    t_end = max(times) + timedelta(seconds=window.buffer_after_sec)

    duration = (t_end - t_start).total_seconds()
    if duration > window.max_duration_sec:
        session = alert.get("checkout_session") or {}
        if session.get("t_start") and session.get("t_end"):
            center = _parse_dt(session["t_start"]) + (
                _parse_dt(session["t_end"]) - _parse_dt(session["t_start"])
            ) / 2
        else:
            center = min(times) + (max(times) - min(times)) / 2
        half = window.max_duration_sec / 2.0
        t_start = center - timedelta(seconds=half)
        t_end = center + timedelta(seconds=half)

    return t_start, t_end


def compute_checkout_range(
    alert: dict[str, Any],
    *,
    window: EvidenceWindow,
) -> tuple[datetime, datetime] | None:
    """Janela curta focada na sessão de checkout (cam2)."""
    session = alert.get("checkout_session") or {}
    if not session.get("t_start") or not session.get("t_end"):
        return None
    t_start = _parse_dt(session["t_start"]) - timedelta(
        seconds=window.checkout_buffer_before_sec
    )
    t_end = _parse_dt(session["t_end"]) + timedelta(
        seconds=window.checkout_buffer_after_sec
    )
    return t_start, t_end
