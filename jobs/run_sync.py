#!/usr/bin/env python3
"""Job Fase 1: constrói sync_map a partir do vídeo."""

from __future__ import annotations

import argparse
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
from track_fraude.pipeline.state import sync_phase_status
from track_fraude.storage import (
    FilePipelineStateRepository,
    FileSyncMapRepository,
    ProcessedScope,
    processed_root,
)
from track_fraude.sync import build_sync_map, save_sync_map
from track_fraude.video_paths import resolve_video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera sync_map.json para uma câmera.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--camera", required=True, help="ID da câmera cadastrada")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--video", default=None, help="Caminho do vídeo")
    args = parser.parse_args()

    config = load_job_store_config(args)
    validate_camera_in_config(config, args.camera)
    camera_ids = camera_ids_from_config(config)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)
    video_path = resolve_video_path(
        ROOT, date=args.date, camera_id=args.camera, video=args.video
    )

    if not video_path.exists():
        raise FileNotFoundError(
            f"Vídeo não encontrado: {video_path}. "
            f"Execute: python tools/generate_test_video.py "
            f"--store-id {config['store_id']} --camera {args.camera} --date {args.date}"
        )

    sync_map = build_sync_map(
        camera_id=args.camera,
        date=args.date,
        video_path=video_path,
        config=config,
    )

    output_path = scope.sync_map_path(args.date, args.camera)
    save_sync_map(sync_map, output_path)

    sync_repo = FileSyncMapRepository(scope)
    sync_repo.save(args.camera, args.date, sync_map.to_dict())

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.init_if_missing(args.date, camera_ids)
    state["cameras"][args.camera]["sync"] = "completed"
    state["phases"]["sync"]["status"] = sync_phase_status(state, camera_ids)
    state_repo.save(args.date, state)

    print(f"sync_map salvo em: {output_path}")
    print(f"anchor: frame {sync_map.anchor.frame_idx} -> {sync_map.anchor.t_abs.isoformat()}")
    print(f"method: {sync_map.build_method} | samples: {len(sync_map.samples)}")


if __name__ == "__main__":
    main()
