#!/usr/bin/env python3
"""Valida sync_map + consulta POS por intervalo (Fase 1)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.models.sync import SyncMap
from track_fraude.pos import FilePosClient
from track_fraude.storage import ProcessedScope, processed_root
from track_fraude.sync import load_sync_map


def parse_time_arg(value: str, date: str) -> datetime:
    if "T" in value:
        return datetime.fromisoformat(value)
    return datetime.fromisoformat(f"{date}T{value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida timestamp de frame e consulta POS no intervalo."
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--camera", default="cam2")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--frame", type=int, default=None)
    parser.add_argument("--time", default=None, help="HH:MM:SS ou ISO")
    parser.add_argument("--lane", type=int, default=3)
    parser.add_argument("--from-time", default="06:10:00")
    parser.add_argument("--to-time", default="06:15:00")
    parser.add_argument("--delta-sec", type=int, default=None)
    args = parser.parse_args()

    config = load_job_store_config(args)
    store_id = config["store_id"]
    delta = args.delta_sec or int(config.get("sync", {}).get("pos_match_delta_sec", 60))
    scope = ProcessedScope.from_config(processed_root(ROOT), config)

    sync_path = scope.sync_map_path(args.date, args.camera)
    sync_map: SyncMap = load_sync_map(sync_path)

    print("=== SYNC MAP ===")
    print(f"camera: {sync_map.camera_id}")
    print(f"video:  {sync_map.video_path}")
    print(f"fps:    {sync_map.fps}")
    print(f"method: {sync_map.build_method}")
    print(f"anchor: frame {sync_map.anchor.frame_idx} = {sync_map.anchor.t_abs.isoformat()}")

    if args.frame is not None:
        ts = sync_map.timestamp_at_frame(args.frame)
        print(f"\nFrame {args.frame} -> {ts.isoformat(sep=' ', timespec='seconds')}")

    if args.time is not None:
        target = parse_time_arg(args.time, args.date)
        frame = sync_map.frame_at_timestamp(target)
        print(
            f"\nHorário {target.isoformat(sep=' ', timespec='seconds')} -> frame ~{frame}"
        )

    t_from = parse_time_arg(args.from_time, args.date) - timedelta(seconds=delta)
    t_to = parse_time_arg(args.to_time, args.date) + timedelta(seconds=delta)

    pos = FilePosClient(ROOT / "data" / "pos")
    matches = pos.get_transactions_between(
        store_id=store_id,
        date=args.date,
        t_from=t_from,
        t_to=t_to,
        lane_id=args.lane,
    )

    print("\n=== POS QUERY ===")
    print(f"intervalo consultado: {t_from.isoformat()} -> {t_to.isoformat()}")
    print(f"lane_id: {args.lane} | delta: {delta}s")
    if not matches:
        print("resultado: nenhuma venda paga encontrada")
    else:
        for tx in matches:
            print(
                f"- {tx.transaction_id} | {tx.t_sale.isoformat()} | "
                f"lane {tx.lane_id} | qty {tx.qty_total} | R$ {tx.total_value:.2f}"
            )


if __name__ == "__main__":
    main()
