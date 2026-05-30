#!/usr/bin/env python3
"""Job Fase 4: Re-ID cross-camera → persons.json + cross_camera_links.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.merge import apply_persons_to_timelines, build_persons_document, resolve_merge_cameras
from track_fraude.merge.builder import load_video_path_from_manifest
from track_fraude.storage import (
    FilePipelineStateRepository,
    FileTrackRepository,
    ProcessedScope,
    processed_root,
)
from track_fraude.video_paths import resolve_video_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Associa tracks cam1↔cam2 e gera global_person_id."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument(
        "--max-travel-sec",
        type=float,
        default=1800.0,
        help="Janela máxima entre entrada (cam1) e checkout (cam2) em segundos",
    )
    parser.add_argument(
        "--min-appearance-score",
        type=float,
        default=0.0,
        help="Similaridade mínima de aparência (0=desliga filtro visual)",
    )
    parser.add_argument(
        "--skip-appearance",
        action="store_true",
        help="Usa só janela temporal (não lê vídeo para histograma HSV)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    entrance_camera, checkout_camera = resolve_merge_cameras(config)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)
    track_repo = FileTrackRepository(scope)

    for camera_id in (entrance_camera, checkout_camera):
        tracks_path = scope.tracks_path(args.date, camera_id)
        if not tracks_path.exists():
            raise FileNotFoundError(
                f"tracks.parquet não encontrado: {tracks_path}. "
                f"Execute run_track.py --camera {camera_id} ..."
            )

    entrance_rows = track_repo.load_tracks(entrance_camera, args.date)
    checkout_rows = track_repo.load_tracks(checkout_camera, args.date)

    timelines = None
    timelines_path = scope.timelines_path(args.date)
    if timelines_path.exists():
        with timelines_path.open(encoding="utf-8") as handle:
            timelines = json.load(handle)

    entrance_video = None
    checkout_video = None
    if not args.skip_appearance:
        entrance_manifest = scope.manifest_path(args.date, entrance_camera)
        checkout_manifest = scope.manifest_path(args.date, checkout_camera)
        entrance_video = load_video_path_from_manifest(entrance_manifest) or resolve_video_path(
            ROOT,
            date=args.date,
            camera_id=entrance_camera,
            store_id=config["store_id"],
            group_code=config.get("group_code"),
        )
        checkout_video = load_video_path_from_manifest(checkout_manifest) or resolve_video_path(
            ROOT,
            date=args.date,
            camera_id=checkout_camera,
            store_id=config["store_id"],
            group_code=config.get("group_code"),
        )

    persons_doc, links_doc = build_persons_document(
        date=args.date,
        store_id=config["store_id"],
        group_code=config["group_code"],
        entrance_camera=entrance_camera,
        checkout_camera=checkout_camera,
        entrance_rows=entrance_rows,
        checkout_rows=checkout_rows,
        timelines=timelines,
        entrance_video=entrance_video,
        checkout_video=checkout_video,
        max_travel_sec=args.max_travel_sec,
        min_appearance_score=args.min_appearance_score,
    )

    merge_dir = scope.merge_dir(args.date)
    merge_dir.mkdir(parents=True, exist_ok=True)

    persons_path = scope.persons_path(args.date)
    links_path = scope.cross_camera_links_path(args.date)
    with persons_path.open("w", encoding="utf-8") as handle:
        json.dump(persons_doc, handle, indent=2, ensure_ascii=False)
    with links_path.open("w", encoding="utf-8") as handle:
        json.dump(links_doc, handle, indent=2, ensure_ascii=False)

    if timelines is not None:
        enriched = apply_persons_to_timelines(timelines, persons_doc)
        with timelines_path.open("w", encoding="utf-8") as handle:
            json.dump(enriched, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.load(args.date)
    state["phases"]["merge"]["status"] = "completed"
    state_repo.save(args.date, state)

    print(f"persons salvos em: {persons_path}")
    print(f"links salvos em: {links_path}")
    print(
        f"pessoas: {persons_doc['person_count']} | "
        f"links cross-camera: {persons_doc['cross_camera_link_count']}"
    )
    if timelines is not None:
        print(f"timelines atualizado com global_person_id: {timelines_path}")


if __name__ == "__main__":
    main()
