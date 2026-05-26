#!/usr/bin/env python3
"""Job Fase 3: enriquece checkout_sessions com pos_matches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.pos import DEFAULT_POS_API_URL, create_pos_client
from track_fraude.pos_match import enrich_timelines_with_pos
from track_fraude.storage import FilePipelineStateRepository, ProcessedScope, processed_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Associa transações POS às sessões de checkout."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument(
        "--pos-root",
        default=str(ROOT / "data" / "pos"),
        help="Pasta raiz do JSON POS (modo arquivo, default: data/pos)",
    )
    parser.add_argument(
        "--pos-api-url",
        default=None,
        help=f"URL da API POS provisória (ex.: {DEFAULT_POS_API_URL}). Se informado, ignora --pos-root.",
    )
    parser.add_argument(
        "--delta-sec",
        type=int,
        default=None,
        help="Margem δ em segundos (default: pos_match_delta_sec da loja)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)
    timelines_path = scope.timelines_path(args.date)
    if not timelines_path.exists():
        raise FileNotFoundError(
            f"timelines.json não encontrado: {timelines_path}. "
            f"Execute: python jobs/run_events.py --date {args.date} --camera cam2 ..."
        )

    with timelines_path.open(encoding="utf-8") as handle:
        timelines = json.load(handle)

    delta_sec = args.delta_sec or int(
        config.get("sync", {}).get("pos_match_delta_sec", 60)
    )
    pos_client = create_pos_client(
        pos_root=args.pos_root,
        pos_api_url=args.pos_api_url,
    )
    enriched = enrich_timelines_with_pos(
        timelines,
        store_id=config["store_id"],
        date=args.date,
        pos_client=pos_client,
        delta_sec=delta_sec,
    )

    with timelines_path.open("w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.load(args.date)
    state["phases"]["pos_match"]["status"] = "completed"
    state_repo.save(args.date, state)

    matched_sessions = sum(
        1
        for track in enriched.get("tracks", [])
        for session in track.get("checkout_sessions", [])
        if session.get("pos_matches")
    )
    print(f"timelines atualizado em: {timelines_path}")
    print(f"sessões com venda POS: {matched_sessions} | δ={delta_sec}s")


if __name__ == "__main__":
    main()
