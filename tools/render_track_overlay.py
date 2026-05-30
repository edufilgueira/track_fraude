#!/usr/bin/env python3
"""Overlay de debug: bbox + track_id sobre o vídeo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import (
    add_store_cli_args,
    load_job_store_config,
    validate_camera_in_config,
)
from track_fraude.storage import ProcessedScope, processed_root
from track_fraude.track import group_by_frame, read_tracks_parquet
from track_fraude.video_paths import resolve_video_path

COLORS = [
    (0, 255, 0),
    (255, 128, 0),
    (0, 128, 255),
    (255, 0, 128),
    (128, 255, 0),
    (255, 255, 0),
    (128, 0, 255),
]


def color_for_track(track_id: int) -> tuple[int, int, int]:
    return COLORS[track_id % len(COLORS)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza overlay de tracks no vídeo.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--camera", required=True, help="ID da câmera")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--video", default=None, help="Caminho do vídeo de entrada")
    parser.add_argument(
        "--output",
        default=None,
        help="Caminho do MP4 de saída (default: {camera}_tracked.mp4 na pasta do vídeo)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    validate_camera_in_config(config, args.camera)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)

    tracks_path = scope.tracks_path(args.date, args.camera)
    if not tracks_path.exists():
        raise FileNotFoundError(
            f"tracks.parquet não encontrado: {tracks_path}. "
            f"Execute: python jobs/run_track.py --date {args.date} --camera {args.camera} ..."
        )

    video_path = resolve_video_path(
        ROOT,
        date=args.date,
        camera_id=args.camera,
        store_id=config["store_id"],
        group_code=config.get("group_code"),
        video=args.video,
    )
    if not video_path.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")

    output_path = (
        Path(args.output)
        if args.output
        else video_path.with_name(f"{args.camera}_tracked.mp4")
    )

    by_frame = group_by_frame(read_tracks_parquet(tracks_path))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        for det in by_frame.get(frame_idx, []):
            x1, y1, x2, y2 = int(det["x1"]), int(det["y1"]), int(det["x2"]), int(det["y2"])
            track_id = int(det["track_id"])
            color = color_for_track(track_id)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"id={track_id}"
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 8, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()
    print(f"overlay salvo em: {output_path}")


if __name__ == "__main__":
    main()
