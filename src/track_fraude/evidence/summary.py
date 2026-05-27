from __future__ import annotations

from datetime import datetime
from typing import Any


def _fmt_time(value: str | datetime) -> str:
    dt = datetime.fromisoformat(str(value)) if not isinstance(value, datetime) else value
    return dt.strftime("%H:%M:%S")


def _event_label(event: dict[str, Any]) -> str:
    kind = str(event.get("event", ""))
    zone = event.get("zone_id") or event.get("mode") or "zona"
    if kind == "entered":
        return f"Entrou na loja ({zone})"
    if kind == "left":
        return f"Saiu da loja ({zone})"
    return f"{kind} ({zone})"


def build_timeline_payload(alert: dict[str, Any]) -> dict[str, Any]:
    session = alert.get("checkout_session") or {}
    return {
        "alert_id": alert.get("alert_id"),
        "rule_id": alert.get("rule_id"),
        "severity": alert.get("severity"),
        "date": alert.get("date"),
        "global_person_id": alert.get("global_person_id"),
        "track_key": alert.get("track_key"),
        "checkout_session": session,
        "store_timeline": alert.get("store_timeline") or [],
    }


def build_pos_context(alert: dict[str, Any]) -> dict[str, Any]:
    session = alert.get("checkout_session") or {}
    return {
        "alert_id": alert.get("alert_id"),
        "lane_id": session.get("lane_id"),
        "checkout_window": {
            "t_start": session.get("t_start"),
            "t_end": session.get("t_end"),
        },
        "pos_matches": alert.get("pos_matches") or [],
        "pos_match_count": len(alert.get("pos_matches") or []),
    }


def build_summary_text(alert: dict[str, Any]) -> str:
    lines = [
        f"Alerta {alert.get('alert_id')} | Regra: {alert.get('rule_id')} | "
        f"Severidade: {alert.get('severity', 'high')}",
        "",
    ]
    if alert.get("global_person_id"):
        lines.append(f"Pessoa unificada: {alert['global_person_id']}")
        lines.append("")

    for event in alert.get("store_timeline") or []:
        if not event.get("t"):
            continue
        lines.append(f"{_fmt_time(event['t'])} — {_event_label(event)} (cam1)")

    session = alert.get("checkout_session") or {}
    if session.get("t_start"):
        lane = session.get("lane_id", "?")
        lines.append(
            f"{_fmt_time(session['t_start'])} — Iniciou permanência no caixa {lane} (cam2)"
        )
    if session.get("t_end"):
        duration = session.get("duration_sec", 0)
        lane = session.get("lane_id", "?")
        lines.append(
            f"{_fmt_time(session['t_end'])} — Saiu do caixa {lane} "
            f"(duração: {duration:.0f}s)"
        )

    lines.append("")
    pos_matches = alert.get("pos_matches") or []
    if pos_matches:
        lines.append(f"POS: {len(pos_matches)} transação(ões) no intervalo.")
    else:
        lines.append("POS: Nenhuma venda registrada no intervalo da sessão de caixa.")

    lines.extend(["", alert.get("summary", ""), "", "Vídeos: cam1_clip.mp4 | cam2_clip.mp4"])
    if session.get("t_start"):
        lines.append("Checkout focado: cam2_checkout_clip.mp4")
    return "\n".join(line for line in lines if line is not None)
