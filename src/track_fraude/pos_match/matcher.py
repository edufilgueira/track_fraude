from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from track_fraude.models.pos import Transaction
from track_fraude.pos import FilePosClient


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def transaction_to_match(tx: Transaction) -> dict[str, Any]:
    return {
        "transaction_id": tx.transaction_id,
        "t_sale": tx.t_sale.isoformat(),
        "lane_id": tx.lane_id,
        "qty_total": tx.qty_total,
        "total_value": tx.total_value,
        "status": tx.status,
    }


def match_session_to_pos(
    session: dict[str, Any],
    *,
    store_id: str,
    date: str,
    pos_client: FilePosClient,
    delta_sec: int,
) -> list[dict[str, Any]]:
    t_start = _parse_dt(session["t_start"])
    t_end = _parse_dt(session["t_end"])
    lane_id = int(session["lane_id"])
    delta = timedelta(seconds=delta_sec)

    matches = pos_client.get_transactions_between(
        store_id=store_id,
        date=date,
        t_from=t_start - delta,
        t_to=t_end + delta,
        lane_id=lane_id,
    )
    return [transaction_to_match(tx) for tx in matches]


def enrich_timelines_with_pos(
    timelines: dict[str, Any],
    *,
    store_id: str,
    date: str,
    pos_client: FilePosClient,
    delta_sec: int,
) -> dict[str, Any]:
    payload = dict(timelines)
    enriched_tracks: list[dict[str, Any]] = []

    for track in timelines.get("tracks", []):
        track_copy = dict(track)
        sessions: list[dict[str, Any]] = []
        for session in track.get("checkout_sessions", []):
            session_copy = dict(session)
            session_copy["pos_matches"] = match_session_to_pos(
                session_copy,
                store_id=store_id,
                date=date,
                pos_client=pos_client,
                delta_sec=delta_sec,
            )
            sessions.append(session_copy)
        track_copy["checkout_sessions"] = sessions
        enriched_tracks.append(track_copy)

    payload["tracks"] = enriched_tracks
    payload["pos_match"] = {
        "delta_sec": delta_sec,
        "matched_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload
