#!/usr/bin/env python3
"""Job Fase 3: aplica regra R1 e gera alerts/index.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.alerts import build_alerts_index
from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.storage import (
    FilePipelineStateRepository,
    ProcessedScope,
    processed_root,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera alertas R1 a partir de timelines.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    args = parser.parse_args()

    config = load_job_store_config(args)
    min_duration_sec = float(config["sync"]["r1_min_checkout_duration_sec"])

    processed = ProcessedScope.from_config(processed_root(ROOT), config)

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

    index = build_alerts_index(
        timelines,
        date=args.date,
        store_id=config["store_id"],
        group_code=config["group_code"],
        min_duration_sec=min_duration_sec,
    )

    index_path = processed.alerts_index_path(args.date)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(processed)
    state = state_repo.load(args.date)
    state["phases"]["alerts"]["status"] = "completed"
    state_repo.save(args.date, state)

    print(f"alertas salvos em: {index_path}")
    print(f"total R1: {index['alert_count']}")


if __name__ == "__main__":
    main()
