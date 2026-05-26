#!/usr/bin/env python3
"""Job Fase 3: tracks + zonas → timelines.json (FSM com histerese)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import (
    add_store_cli_args,
    camera_ids_from_config,
    load_job_store_config,
    validate_camera_in_config,
)
from track_fraude.events import build_timelines_document
from track_fraude.pipeline.state import events_phase_status
from track_fraude.storage import (
    FilePipelineStateRepository,
    FileTrackRepository,
    ProcessedScope,
    processed_root,
)
from track_fraude.zones import resolve_zones_for_job


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera timeline de eventos (checkout_sessions, entered/left)."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--camera", required=True, help="ID da câmera cadastrada")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument(
        "--zones",
        default=None,
        help="Caminho opcional a um JSON de zonas (default: SQLite da loja)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    validate_camera_in_config(config, args.camera)
    camera_ids = camera_ids_from_config(config)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)

    tracks_path = scope.tracks_path(args.date, args.camera)
    if not tracks_path.exists():
        raise FileNotFoundError(
            f"tracks.parquet não encontrado: {tracks_path}. "
            f"Execute: python jobs/run_track.py --date {args.date} --camera {args.camera} ..."
        )

    zones = resolve_zones_for_job(
        config=config,
        project_root=ROOT,
        zones_path=Path(args.zones) if args.zones else None,
    )
    if args.camera not in zones.cameras:
        raise ValueError(
            f"Câmera {args.camera!r} sem zonas configuradas. "
            "Defina polígonos no painel web (Editar câmera → Definir zona)."
        )

    track_repo = FileTrackRepository(scope)
    track_rows = track_repo.load_tracks(args.camera, args.date)

    timelines_path = scope.timelines_path(args.date)
    existing = None
    if timelines_path.exists():
        with timelines_path.open(encoding="utf-8") as handle:
            existing = json.load(handle)

    payload = build_timelines_document(
        zones=zones,
        camera_id=args.camera,
        date=args.date,
        store_id=config["store_id"],
        group_code=config["group_code"],
        track_rows=track_rows,
        existing=existing,
    )

    timelines_path.parent.mkdir(parents=True, exist_ok=True)
    with timelines_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.init_if_missing(args.date, camera_ids)
    state["cameras"][args.camera]["events"] = "completed"
    state["phases"]["events"]["status"] = events_phase_status(state, camera_ids)
    state_repo.save(args.date, state)

    session_count = sum(
        len(track.get("checkout_sessions", [])) for track in payload.get("tracks", [])
    )
    print(f"timelines salvo em: {timelines_path}")
    print(
        f"tracks processados: {len(payload.get('tracks', []))} | "
        f"checkout_sessions: {session_count}"
    )


if __name__ == "__main__":
    main()
