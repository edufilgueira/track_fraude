#!/usr/bin/env python3
"""Job Fase 2: YOLOv8 + ByteTrack → tracks.parquet + manifest.json."""

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
from track_fraude.pipeline.state import track_phase_status
from track_fraude.storage import (
    FilePipelineStateRepository,
    FileTrackRepository,
    ProcessedScope,
    processed_root,
)
from track_fraude.sync.sync_map_builder import load_sync_map
from track_fraude.track import TrackRunConfig, build_manifest, run_tracking
from track_fraude.video_paths import resolve_video_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rastreia pessoas em uma câmera (YOLOv8 + ByteTrack)."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--camera", required=True, help="ID da câmera cadastrada")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--video", default=None, help="Caminho do vídeo")
    parser.add_argument("--model", default="yolov8n.pt", help="Modelo YOLO (default: yolov8n.pt)")
    parser.add_argument("--conf", type=float, default=0.5, help="Confiança mínima YOLO")
    parser.add_argument(
        "--tracker",
        default="bytetrack.yaml",
        help="Tracker Ultralytics (default: bytetrack.yaml)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    validate_camera_in_config(config, args.camera)
    camera_ids = camera_ids_from_config(config)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)

    track_settings = config.get("track") or {}
    vid_stride = max(1, int(track_settings.get("vid_stride", 5)))

    video_path = resolve_video_path(
        ROOT,
        date=args.date,
        camera_id=args.camera,
        store_id=config["store_id"],
        group_code=config.get("group_code"),
        video=args.video,
    )
    if not video_path.exists():
        raise FileNotFoundError(
            f"Vídeo não encontrado: {video_path}. "
            f"Execute: python tools/generate_test_video.py "
            f"--store-id {config['store_id']} --camera {args.camera} --date {args.date}"
        )

    sync_path = scope.sync_map_path(args.date, args.camera)
    if not sync_path.exists():
        raise FileNotFoundError(
            f"sync_map não encontrado: {sync_path}. "
            f"Execute: python jobs/run_sync.py --date {args.date} --camera {args.camera} "
            f"--store-id {config['store_id']} --group-code {config.get('group_code', 'default')}"
        )

    sync_map = load_sync_map(sync_path)
    track_config = TrackRunConfig(
        model_name=args.model,
        tracker=args.tracker,
        vid_stride=vid_stride,
        conf=args.conf,
    )

    rows, stats = run_tracking(
        video_path=video_path,
        sync_map=sync_map,
        config=track_config,
    )

    track_repo = FileTrackRepository(scope)
    tracks_path = track_repo.save_tracks(args.camera, args.date, rows)

    manifest = build_manifest(
        camera_id=args.camera,
        date=args.date,
        video_path=video_path,
        sync_map_path=sync_path,
        tracks_path=tracks_path,
        config=track_config,
        stats=stats,
        frame_count=sync_map.frame_count,
    )
    manifest_path = scope.manifest_path(args.date, args.camera)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.init_if_missing(args.date, camera_ids)
    state["cameras"][args.camera]["track"] = "completed"
    state["phases"]["track"]["status"] = track_phase_status(state, camera_ids)
    state_repo.save(args.date, state)

    print(f"tracks salvo em: {tracks_path}")
    print(f"manifest salvo em: {manifest_path}")
    print(
        f"detecções: {stats['detection_count']} | "
        f"tracks únicos: {stats['unique_tracks']} | "
        f"vid_stride: {track_config.vid_stride}"
    )


if __name__ == "__main__":
    main()
