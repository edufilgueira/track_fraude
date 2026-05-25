#!/usr/bin/env python3
"""Gera vídeo de teste com timestamp embutido (ROI superior)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import (
    add_store_cli_args,
    load_job_store_config,
    validate_camera_in_config,
)
from track_fraude.sync.sync_map_builder import roi_from_config


def format_timestamp(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S")


def _video_codecs() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("mp4v", "avc1", "H264")
    return ("avc1", "H264", "mp4v")


def _open_video_writer(output_path: Path, fps: int, size: tuple[int, int]):
    width, height = size
    for codec in _video_codecs():
        writer = cv2.VideoWriter(
            str(output_path),
            cv2.VideoWriter_fourcc(*codec),
            fps,
            (width, height),
        )
        if writer.isOpened():
            return writer
    raise RuntimeError("Não foi possível criar VideoWriter (instale codec H.264 ou mp4v)")


def generate_video(
    *,
    output_path: Path,
    camera_id: str,
    start_time: datetime,
    duration_sec: int,
    fps: int,
    config: dict,
) -> None:
    roi = roi_from_config(camera_id, config)

    width, height = 1280, 720
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = _open_video_writer(output_path, fps, (width, height))

    total_frames = duration_sec * fps
    for frame_idx in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (40, 40, 40)

        current_time = start_time + timedelta(seconds=frame_idx / fps)
        text = format_timestamp(current_time)

        cv2.rectangle(
            frame,
            (roi.x - 2, roi.y - 2),
            (roi.x + roi.width + 2, roi.y + roi.height + 2),
            (0, 0, 0),
            -1,
        )
        cv2.putText(
            frame,
            text,
            (roi.x + 8, roi.y + 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"{camera_id} | frame {frame_idx}",
            (20, height - 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )
        writer.write(frame)

    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera vídeo de teste com timestamp.")
    parser.add_argument("--camera", default="cam2", help="ID da câmera cadastrada")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--date", default="2026-05-22")
    parser.add_argument("--start-time", default="2026-05-22T06:10:00")
    parser.add_argument("--duration-sec", type=int, default=420)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument(
        "--output",
        default=None,
        help="Caminho do mp4 (default: data/raw/video/{date}/{camera}.mp4)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    validate_camera_in_config(config, args.camera)

    output = (
        Path(args.output)
        if args.output
        else ROOT
        / "data"
        / "raw"
        / "video"
        / args.date
        / f"{args.camera}.mp4"
    )
    start_time = datetime.fromisoformat(args.start_time)

    generate_video(
        output_path=output,
        camera_id=args.camera,
        start_time=start_time,
        duration_sec=args.duration_sec,
        fps=args.fps,
        config=config,
    )
    print(f"Vídeo gerado: {output}")


if __name__ == "__main__":
    main()
