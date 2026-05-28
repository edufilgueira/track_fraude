#!/usr/bin/env python3
"""Job Fase 6: aplica regras R1–R5 e gera alerts/index.json."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.alerts import AlertRuleConfig, build_alerts_index
from track_fraude.alerts.store_config import alert_rule_config_from_store
from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.pos import FilePosClient
from track_fraude.storage import (
    FilePipelineStateRepository,
    ProcessedScope,
    processed_root,
)
from track_fraude.track.parquet_io import read_tracks_parquet


def _load_entrance_track_rows(processed: ProcessedScope, date: str, timelines: dict) -> dict[str, list[dict]]:
    entrance_camera = str(
        timelines.get("persons_ref", {}).get("entrance_camera", "cam1")
    )
    parquet_path = processed.tracks_path(date, entrance_camera)
    if not parquet_path.exists():
        return {}

    rows = read_tracks_parquet(parquet_path)
    by_track_id: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_track_id[int(row["track_id"])].append(row)

    rows_by_key: dict[str, list[dict]] = {}
    for track in timelines.get("tracks", []):
        if track.get("camera_id") != entrance_camera:
            continue
        track_key = str(track.get("track_key"))
        track_id = int(track.get("track_id", 0))
        if track_id in by_track_id:
            rows_by_key[track_key] = by_track_id[track_id]
    return rows_by_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera alertas R1–R5 a partir de timelines.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--pos-root",
        default=str(ROOT / "data" / "pos"),
        help="Raiz dos JSON de POS",
    )
    parser.add_argument(
        "--t-return-sec",
        type=float,
        default=None,
        help="Override R1b (default: valor da loja no SQLite)",
    )
    parser.add_argument(
        "--no-require-left",
        action="store_true",
        help="Emite R2/R5 sem evento left (somente testes)",
    )
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    args = parser.parse_args()

    config_store = load_job_store_config(args)
    rule_config = alert_rule_config_from_store(
        config_store,
        require_left_store=not args.no_require_left,
    )
    if args.t_return_sec is not None:
        rule_config = replace(rule_config, t_return_sec=float(args.t_return_sec))

    processed = ProcessedScope.from_config(processed_root(ROOT), config_store)
    timelines_path = processed.timelines_path(args.date)
    if not timelines_path.exists():
        raise FileNotFoundError(
            f"timelines.json não encontrado: {timelines_path}. "
            f"Execute run_events.py e run_pos_match.py antes."
        )

    with timelines_path.open(encoding="utf-8") as handle:
        timelines = json.load(handle)

    if not any(
        "pos_matches" in session
        for track in timelines.get("tracks", [])
        for session in track.get("checkout_sessions", [])
    ):
        raise FileNotFoundError(
            "checkout_sessions sem pos_matches. "
            f"Execute: python jobs/run_pos_match.py --date {args.date} ..."
        )

    pos_client = FilePosClient(args.pos_root)
    track_rows_by_key = _load_entrance_track_rows(processed, args.date, timelines)

    index = build_alerts_index(
        timelines,
        date=args.date,
        store_id=config_store["store_id"],
        group_code=config_store["group_code"],
        config=rule_config,
        pos_client=pos_client,
        track_rows_by_key=track_rows_by_key or None,
    )

    index_path = processed.alerts_index_path(args.date)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(processed)
    state = state_repo.load(args.date)
    state["phases"]["alerts"]["status"] = "completed"
    state_repo.save(args.date, state)

    by_rule: dict[str, int] = defaultdict(int)
    for alert in index["alerts"]:
        by_rule[str(alert.get("rule_id"))] += 1

    print(f"alertas salvos em: {index_path}")
    print(f"total: {index['alert_count']}")
    for rule_id in sorted(by_rule):
        print(f"  {rule_id}: {by_rule[rule_id]}")


if __name__ == "__main__":
    main()
