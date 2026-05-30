#!/usr/bin/env python3
"""Job Fase 6: enriquece timelines com vision_signals (bbox + YOLO cam1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.storage import ProcessedScope, processed_root
from track_fraude.sync import load_sync_map
from track_fraude.track.parquet_io import read_tracks_parquet
from track_fraude.video_paths import resolve_video_path
from track_fraude.vision.builder import enrich_track_vision_signals


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calcula vision_signals (bbox + YOLO) e grava em timelines.json."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--video", default=None, help="Caminho do vídeo cam1 (opcional)")
    parser.add_argument("--model", default="yolov8n.pt", help="Modelo YOLO (default: yolov8n.pt)")
    parser.add_argument("--conf", type=float, default=0.35, help="Confiança mínima YOLO")
    parser.add_argument(
        "--skip-yolo",
        action="store_true",
        help="Usa apenas proxy bbox (sem inferência YOLO)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    processed = ProcessedScope.from_config(processed_root(ROOT), config)
    timelines_path = processed.timelines_path(args.date)
    if not timelines_path.exists():
        raise FileNotFoundError(f"timelines.json não encontrado: {timelines_path}")

    with timelines_path.open(encoding="utf-8") as handle:
        timelines = json.load(handle)

    entrance_camera = str(
        timelines.get("persons_ref", {}).get("entrance_camera", "cam1")
    )
    parquet_path = processed.tracks_path(args.date, entrance_camera)
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"tracks.parquet não encontrado para {entrance_camera}: {parquet_path}"
        )

    rows = read_tracks_parquet(parquet_path)
    rows_by_track: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_track.setdefault(int(row["track_id"]), []).append(row)

    sync_map = None
    sync_path = processed.sync_map_path(args.date, entrance_camera)
    if sync_path.is_file():
        sync_map = load_sync_map(sync_path)
    elif not args.skip_yolo:
        print(f"AVISO: sync_map ausente ({sync_path}); YOLO desabilitado.")

    video_path = resolve_video_path(
        ROOT,
        date=args.date,
        camera_id=entrance_camera,
        store_id=config["store_id"],
        group_code=config.get("group_code"),
        video=args.video,
    )
    use_yolo = not args.skip_yolo and sync_map is not None
    if use_yolo and not video_path.is_file():
        print(f"AVISO: vídeo ausente ({video_path}); YOLO desabilitado.")
        use_yolo = False

    updated = 0
    yolo_ran = 0
    for track in timelines.get("tracks", []):
        if track.get("camera_id") != entrance_camera:
            continue
        track_id = int(track.get("track_id", 0))
        payload = enrich_track_vision_signals(
            track=track,
            track_rows=rows_by_track.get(track_id),
            video_path=video_path if use_yolo else None,
            sync_map=sync_map,
            model_name=args.model,
            conf=args.conf,
            use_yolo=use_yolo,
        )
        if payload is None:
            continue
        track["vision_signals"] = payload
        updated += 1
        if payload.get("source") == "bbox+yolo":
            yolo_ran += 1

    with timelines_path.open("w", encoding="utf-8") as handle:
        json.dump(timelines, handle, indent=2, ensure_ascii=False)

    mode = "bbox+yolo" if use_yolo else "bbox"
    print(
        f"vision_signals atualizados: {updated} tracks ({yolo_ran} com YOLO, modo={mode}) "
        f"em {timelines_path}"
    )


if __name__ == "__main__":
    main()
