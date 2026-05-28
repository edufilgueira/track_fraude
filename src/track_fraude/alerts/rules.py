from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from track_fraude.alerts.config import AlertRuleConfig
from track_fraude.alerts.scoring import compute_suspicion_score, score_band
from track_fraude.alerts.visit import PersonVisit, build_person_visits
from track_fraude.pos.file_client import FilePosClient
from track_fraude.pos_match.matcher import transaction_to_match


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def session_duration_sec(session: dict[str, Any]) -> float:
    if "duration_sec" in session:
        return float(session["duration_sec"])
    t_start = _parse_dt(session["t_start"])
    t_end = _parse_dt(session["t_end"])
    return (t_end - t_start).total_seconds()


def evaluate_r1_session(
    session: dict[str, Any],
    *,
    min_duration_sec: float,
) -> bool:
    if session.get("t_end") is None:
        return False
    duration = session_duration_sec(session)
    if duration <= min_duration_sec:
        return False
    pos_matches = session.get("pos_matches")
    if pos_matches is None:
        return False
    return len(pos_matches) == 0


def is_r1_suppressed_by_r1b(
    session: dict[str, Any],
    all_sessions: list[dict[str, Any]],
    *,
    t_return_sec: float,
) -> bool:
    if session.get("t_end") is None:
        return False
    session_end = _parse_dt(session["t_end"])
    lane_id = int(session["lane_id"])
    for other in all_sessions:
        if other.get("t_start") is None or other.get("t_end") is None:
            continue
        other_start = _parse_dt(other["t_start"])
        if other_start <= session_end:
            continue
        if (other_start - session_end).total_seconds() > t_return_sec:
            continue
        if int(other.get("lane_id", -1)) != lane_id:
            continue
        paid = [
            match
            for match in other.get("pos_matches") or []
            if str(match.get("status", "paid")) in {"paid", "completed"}
        ]
        if paid:
            return True
    return False


def evaluate_r2(visit: PersonVisit, config: AlertRuleConfig) -> bool:
    """Skip checkout: entrou sem pagar, nunca passou no caixa, saiu com carga líquida."""
    if not visit.has_entered_store:
        return False
    if not visit.ready_for_visit_rules(require_left_store=config.require_left_store):
        return False
    if visit.checkout_sessions:
        return False
    if visit.paid_qty_total() > 0:
        return False
    if visit.carry_profile is None:
        return False
    return visit.carry_profile.has_net_carry_theft(
        net_score_threshold=config.net_carry_score_threshold,
        confidence_threshold=config.carry_confidence_threshold,
    )


def evaluate_r3_session(
    session: dict[str, Any],
    visit: PersonVisit,
    config: AlertRuleConfig,
) -> bool:
    paid = [
        match
        for match in session.get("pos_matches") or []
        if str(match.get("status", "paid")) in {"paid", "completed"}
    ]
    if not paid:
        return False
    if visit.carry_profile is None:
        return False
    if visit.carry_profile.confidence < config.carry_confidence_threshold:
        return False
    pos_items = sum(int(match.get("qty_total", 0)) for match in paid)
    visual = visit.carry_profile.visual_estimate
    return pos_items < visual - config.r3_visual_margin


def evaluate_r4_session(session: dict[str, Any], config: AlertRuleConfig) -> bool:
    if not config.enable_r4:
        return False
    paid = [
        match
        for match in session.get("pos_matches") or []
        if str(match.get("status", "paid")) in {"paid", "completed"}
    ]
    if not paid:
        return False
    pos_items = sum(int(match.get("qty_total", 0)) for match in paid)
    if pos_items < config.r4_min_items:
        return False
    duration = session_duration_sec(session)
    return duration < config.r4_fast_duration_sec


def _cancelled_transactions_for_visit(
    visit: PersonVisit,
    *,
    store_id: str,
    date: str,
    pos_client: FilePosClient | None,
    delta_sec: int = 60,
) -> list[dict[str, Any]]:
    if pos_client is None or visit.visit_start is None:
        return []
    t_from = visit.visit_start - timedelta(seconds=delta_sec)
    t_to = visit.visit_end or visit.visit_start
    t_to = t_to + timedelta(seconds=delta_sec)
    cancelled = pos_client.get_transactions_between(
        store_id=store_id,
        date=date,
        t_from=t_from,
        t_to=t_to,
        lane_id=None,
        statuses=["cancelled"],
    )
    return [transaction_to_match(tx) for tx in cancelled]


def evaluate_r5(
    visit: PersonVisit,
    config: AlertRuleConfig,
    *,
    cancelled_transactions: list[dict[str, Any]],
) -> bool:
    if not cancelled_transactions:
        return False
    if not visit.ready_for_visit_rules(require_left_store=config.require_left_store):
        return False
    if visit.carry_profile is None:
        return False
    return visit.carry_profile.has_carry_increase(
        area_ratio_threshold=config.carry_area_ratio_threshold,
        confidence_threshold=config.carry_confidence_threshold,
    )


def _base_track_fields(visit: PersonVisit, *, prefer_checkout: bool = False) -> dict[str, Any]:
    if prefer_checkout and visit.primary_checkout_track:
        track = visit.primary_checkout_track
    else:
        track = visit.primary_checkout_track or visit.cam1_track or {}
    payload: dict[str, Any] = {
        "track_key": track.get("track_key", visit.track_key),
        "track_id": track.get("track_id"),
        "camera_id": track.get("camera_id"),
    }
    if visit.global_person_id:
        payload["global_person_id"] = visit.global_person_id
    if visit.store_timeline:
        payload["store_timeline"] = visit.store_timeline
    if visit.carry_profile:
        payload["vision_signals"] = visit.carry_profile.to_dict()
    return payload


def _build_alert(
    *,
    alert_index: int,
    date: str,
    rule_id: str,
    visit: PersonVisit,
    summary: str,
    config: AlertRuleConfig,
    confidence: float = 1.0,
    checkout_session: dict[str, Any] | None = None,
    pos_matches: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
    prefer_checkout_track: bool = False,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    score = compute_suspicion_score(rule_id, config=config, confidence=confidence)
    severity = score_band(score)
    if rule_id in {"R1", "R2", "R5", "R1+R2"} and score >= 40.0:
        severity = "high"
    payload: dict[str, Any] = {
        "alert_id": f"AL-{date.replace('-', '')}-{alert_index:04d}",
        "rule_id": rule_id,
        "severity": severity,
        "suspicion_score": score,
        "date": date,
        "summary": summary,
        **_base_track_fields(visit, prefer_checkout=prefer_checkout_track),
    }
    if rule_ids:
        payload["rule_ids"] = rule_ids
    if checkout_session is not None:
        payload["checkout_session"] = {
            "session_id": checkout_session.get("session_id"),
            "lane_id": checkout_session.get("lane_id"),
            "zone_id": checkout_session.get("zone_id"),
            "t_start": checkout_session.get("t_start"),
            "t_end": checkout_session.get("t_end"),
            "duration_sec": checkout_session.get("duration_sec"),
        }
    if pos_matches is not None:
        payload["pos_matches"] = pos_matches
    elif checkout_session is not None:
        payload["pos_matches"] = checkout_session.get("pos_matches", [])
    if extra:
        payload.update(extra)
    return payload


def build_r1_alert(
    *,
    alert_index: int,
    date: str,
    track: dict[str, Any],
    session: dict[str, Any],
    store_timeline: list[dict[str, Any]] | None = None,
    config: AlertRuleConfig | None = None,
) -> dict[str, Any]:
    cfg = config or AlertRuleConfig()
    visit = PersonVisit(
        global_person_id=track.get("global_person_id"),
        track_key=str(track.get("track_key")),
        cam2_tracks=[track],
        primary_checkout_track=track,
        store_timeline=list(store_timeline or []),
        checkout_sessions=[session],
    )
    return _build_alert(
        alert_index=alert_index,
        date=date,
        rule_id="R1",
        visit=visit,
        summary=(
            f"Permaneceu no caixa {session.get('lane_id')} "
            f"por {session.get('duration_sec', 0):.0f}s sem venda registrada"
        ),
        config=cfg,
        checkout_session=session,
    )


def _merge_r1_r2_alerts(
    r1: dict[str, Any],
    r2: dict[str, Any],
    *,
    config: AlertRuleConfig,
) -> dict[str, Any]:
    session = r1.get("checkout_session") or {}
    lane = session.get("lane_id", "?")
    duration = session.get("duration_sec", 0)
    vision = r2.get("vision_signals") or r1.get("vision_signals") or {}
    confidence = float(vision.get("confidence", r2.get("suspicion_score", 0) / 40.0))
    score_r1 = compute_suspicion_score("R1", config=config, confidence=1.0)
    score_r2 = compute_suspicion_score("R2", config=config, confidence=confidence)
    combined_score = round(max(score_r1, score_r2), 1)
    severity = "high" if combined_score >= 40.0 else score_band(combined_score)

    merged = dict(r1)
    merged["rule_id"] = "R1+R2"
    merged["rule_ids"] = ["R1", "R2"]
    merged["suspicion_score"] = combined_score
    merged["severity"] = severity
    merged["summary"] = (
        f"Regras R1 e R2: permaneceu no caixa {lane} por {duration:.0f}s sem venda "
        f"registrada; saiu da loja com indício de carga "
        f"(confiança visual {vision.get('confidence', confidence):.2f})."
    )
    if r2.get("vision_signals"):
        merged["vision_signals"] = r2["vision_signals"]
    return merged


def _consolidate_r1_r2(alerts: list[dict[str, Any]], *, config: AlertRuleConfig) -> list[dict[str, Any]]:
    r1_items = [alert for alert in alerts if alert.get("rule_id") == "R1"]
    r2_items = [alert for alert in alerts if alert.get("rule_id") == "R2"]
    others = [alert for alert in alerts if alert.get("rule_id") not in {"R1", "R2"}]

    if not r1_items or not r2_items:
        return alerts

    r2 = r2_items[0]
    merged = [_merge_r1_r2_alerts(r1, r2, config=config) for r1 in r1_items]
    return merged + others


def _collect_visit_alerts(
    visit: PersonVisit,
    *,
    date: str,
    config: AlertRuleConfig,
    store_id: str,
    pos_client: FilePosClient | None,
    cancelled: list[dict[str, Any]],
    seen_r1: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    visit_alerts: list[dict[str, Any]] = []
    alert_index = 0

    for session in visit.checkout_sessions:
        if not evaluate_r1_session(
            session,
            min_duration_sec=config.min_checkout_duration_sec,
        ):
            continue
        if is_r1_suppressed_by_r1b(
            session,
            visit.checkout_sessions,
            t_return_sec=config.t_return_sec,
        ):
            continue
        dedupe = (
            str(visit.global_person_id or visit.track_key),
            str(session.get("session_id", "")),
        )
        if dedupe in seen_r1:
            continue
        seen_r1.add(dedupe)
        visit_alerts.append(
            _build_alert(
                alert_index=alert_index,
                date=date,
                rule_id="R1",
                visit=visit,
                summary=(
                    f"Permaneceu no caixa {session.get('lane_id')} "
                    f"por {session.get('duration_sec', 0):.0f}s sem venda registrada"
                ),
                config=config,
                confidence=1.0,
                checkout_session=session,
                prefer_checkout_track=True,
            )
        )

    if evaluate_r2(visit, config):
        confidence = visit.carry_profile.confidence if visit.carry_profile else 0.0
        visit_alerts.append(
            _build_alert(
                alert_index=alert_index,
                date=date,
                rule_id="R2",
                visit=visit,
                summary=(
                    "Entrou na loja sem passar no caixa, não pagou e "
                    "saiu carregando mais do que na entrada"
                ),
                config=config,
                confidence=confidence,
                pos_matches=[],
            )
        )

    for session in visit.checkout_sessions:
        if evaluate_r3_session(session, visit, config):
            paid = visit.paid_pos_matches()
            pos_items = sum(int(match.get("qty_total", 0)) for match in paid)
            visual = visit.carry_profile.visual_estimate if visit.carry_profile else 0
            confidence = visit.carry_profile.confidence if visit.carry_profile else 0.0
            visit_alerts.append(
                _build_alert(
                    alert_index=alert_index,
                    date=date,
                    rule_id="R3",
                    visit=visit,
                    summary=(
                        f"POS registrou {pos_items} item(ns), "
                        f"estimativa visual ~{visual}"
                    ),
                    config=config,
                    confidence=confidence,
                    checkout_session=session,
                    prefer_checkout_track=True,
                )
            )

        if evaluate_r4_session(session, config):
            paid = [
                match
                for match in session.get("pos_matches") or []
                if str(match.get("status", "paid")) in {"paid", "completed"}
            ]
            pos_items = sum(int(match.get("qty_total", 0)) for match in paid)
            duration = session.get("duration_sec", 0)
            visit_alerts.append(
                _build_alert(
                    alert_index=alert_index,
                    date=date,
                    rule_id="R4",
                    visit=visit,
                    summary=(
                        f"Permaneceu {duration:.0f}s no caixa {session.get('lane_id')} "
                        f"com {pos_items} itens no POS (tempo curto)"
                    ),
                    config=config,
                    confidence=0.85,
                    checkout_session=session,
                    prefer_checkout_track=True,
                )
            )

    if evaluate_r5(visit, config, cancelled_transactions=cancelled):
        confidence = visit.carry_profile.confidence if visit.carry_profile else 0.0
        visit_alerts.append(
            _build_alert(
                alert_index=alert_index,
                date=date,
                rule_id="R5",
                visit=visit,
                summary=(
                    "Transação cancelada no intervalo da visita e "
                    "saída com indício de carga"
                ),
                config=config,
                confidence=confidence,
                pos_matches=cancelled,
                extra={"cancelled_transactions": cancelled},
            )
        )

    return _consolidate_r1_r2(visit_alerts, config=config)


def evaluate_all_alerts(
    timelines: dict[str, Any],
    *,
    date: str,
    config: AlertRuleConfig,
    store_id: str | None = None,
    pos_client: FilePosClient | None = None,
    track_rows_by_key: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    visits = build_person_visits(
        timelines,
        track_rows_by_key=track_rows_by_key,
        area_ratio_threshold=config.carry_area_ratio_threshold,
    )
    alerts: list[dict[str, Any]] = []
    alert_index = 1
    seen_r1: set[tuple[str, str]] = set()

    for visit in visits:
        cancelled = _cancelled_transactions_for_visit(
            visit,
            store_id=store_id or str(timelines.get("store_id", "")),
            date=date,
            pos_client=pos_client,
            delta_sec=config.r5_cancelled_delta_sec,
        )
        visit_alerts = _collect_visit_alerts(
            visit,
            date=date,
            config=config,
            store_id=store_id or str(timelines.get("store_id", "")),
            pos_client=pos_client,
            cancelled=cancelled,
            seen_r1=seen_r1,
        )
        for alert in visit_alerts:
            alert["alert_id"] = f"AL-{date.replace('-', '')}-{alert_index:04d}"
            alerts.append(alert)
            alert_index += 1

    alerts.sort(key=lambda item: (-float(item.get("suspicion_score", 0)), item["alert_id"]))
    return alerts


def evaluate_r1_alerts(
    timelines: dict[str, Any],
    *,
    date: str,
    min_duration_sec: float,
) -> list[dict[str, Any]]:
    config = AlertRuleConfig.from_min_duration(min_duration_sec)
    return [
        alert
        for alert in evaluate_all_alerts(timelines, date=date, config=config)
        if "R1" in (alert.get("rule_ids") or [alert.get("rule_id")])
    ]


def build_alerts_index(
    timelines: dict[str, Any],
    *,
    date: str,
    store_id: str,
    group_code: str,
    min_duration_sec: float | None = None,
    config: AlertRuleConfig | None = None,
    pos_client: FilePosClient | None = None,
    track_rows_by_key: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    cfg = config or AlertRuleConfig.from_min_duration(
        min_duration_sec if min_duration_sec is not None else 60.0
    )
    if min_duration_sec is not None and config is None:
        cfg = AlertRuleConfig.from_min_duration(min_duration_sec)

    alerts = evaluate_all_alerts(
        timelines,
        date=date,
        config=cfg,
        store_id=store_id,
        pos_client=pos_client,
        track_rows_by_key=track_rows_by_key,
    )
    rules = sorted(
        {
            rid
            for alert in alerts
            for rid in (alert.get("rule_ids") or [str(alert.get("rule_id"))])
            if rid
        }
    )
    return {
        "date": date,
        "store_id": store_id,
        "group_code": group_code,
        "rules": rules if rules else ["R1", "R2", "R3", "R4", "R5"],
        "min_checkout_duration_sec": cfg.min_checkout_duration_sec,
        "alert_count": len(alerts),
        "alerts": alerts,
        "rule_config": {
            "t_return_sec": cfg.t_return_sec,
            "carry_confidence_threshold": cfg.carry_confidence_threshold,
            "r3_visual_margin": cfg.r3_visual_margin,
            "r4_min_items": cfg.r4_min_items,
            "r4_fast_duration_sec": cfg.r4_fast_duration_sec,
            "enable_r4": cfg.enable_r4,
            "r5_cancelled_delta_sec": cfg.r5_cancelled_delta_sec,
            "require_left_store": cfg.require_left_store,
        },
    }
