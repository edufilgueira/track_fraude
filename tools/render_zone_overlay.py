#!/usr/bin/env python3
"""Overlay de debug: polígonos + foot point + track_id."""

from __future__ import annotations

import argparse
import sys
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
from track_fraude.storage import ProcessedScope, processed_root
from track_fraude.track import group_by_frame, read_tracks_parquet
from track_fraude.video_paths import resolve_video_path
from track_fraude.zones import foot_point, resolve_zones_for_job

COLORS = [
    (0, 255, 0),
    (255, 128, 0),
    (0, 128, 255),
    (255, 0, 128),
    (128, 255, 0),
    (255, 255, 0),
    (128, 0, 255),
]

LANE_COLORS = [
    (80, 80, 255),
    (80, 255, 80),
    (255, 80, 80),
    (255, 255, 80),
]


def color_for_track(track_id: int) -> tuple[int, int, int]:
    return COLORS[track_id % len(COLORS)]


def draw_zones(frame: np.ndarray, camera_zones) -> None:
    for index, lane in enumerate(camera_zones.checkout_lanes):
        color = LANE_COLORS[index % len(LANE_COLORS)]
        pts = np.array(lane.polygon, dtype=np.int32)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.polylines(frame, [pts], True, color, 2)
        if lane.polygon:
            cx = int(sum(p[0] for p in lane.polygon) / len(lane.polygon))
            cy = int(sum(p[1] for p in lane.polygon) / len(lane.polygon))
            cv2.putText(
                frame,
                f"lane {lane.lane_id}",
                (cx - 30, cy),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )

    if camera_zones.portal is not None:
        pts = np.array(camera_zones.portal.polygon, dtype=np.int32)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], (180, 120, 255))
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.polylines(frame, [pts], True, (180, 120, 255), 2)
        label = camera_zones.portal.label or camera_zones.portal.zone_id
        cv2.putText(
            frame,
            label,
            tuple(map(int, camera_zones.portal.polygon[0])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (180, 120, 255),
            2,
            cv2.LINE_AA,
        )
        if camera_zones.portal.entry_vector is not None:
            cx = int(sum(p[0] for p in camera_zones.portal.polygon) / len(camera_zones.portal.polygon))
            cy = int(sum(p[1] for p in camera_zones.portal.polygon) / len(camera_zones.portal.polygon))
            vx, vy = camera_zones.portal.entry_vector
            scale = 40
            end = (int(cx + vx * scale), int(cy + vy * scale))
            cv2.arrowedLine(frame, (cx, cy), end, (255, 255, 255), 2, tipLength=0.3)
        return

    for zone in (camera_zones.entrance, camera_zones.exit):
        if zone is None:
            continue
        pts = np.array(zone.polygon, dtype=np.int32)
        cv2.polylines(frame, [pts], True, (200, 200, 200), 2)
        cv2.putText(
            frame,
            zone.zone_id,
            tuple(map(int, zone.polygon[0])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (220, 220, 220),
            2,
            cv2.LINE_AA,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Renderiza overlay de zonas + foot point + track_id."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--camera", required=True, help="ID da câmera")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument("--video", default=None, help="Caminho do vídeo de entrada")
    parser.add_argument(
        "--output",
        default=None,
        help="Caminho do MP4 de saída (default: {camera}_zones.mp4 na pasta do vídeo)",
    )
    parser.add_argument(
        "--zones",
        default=None,
        help="Caminho opcional a um JSON de zonas (default: SQLite da loja)",
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

    zones = resolve_zones_for_job(
        config=config,
        project_root=ROOT,
        zones_path=Path(args.zones) if args.zones else None,
    )
    camera_zones = zones.camera(args.camera)

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
        else video_path.with_name(f"{args.camera}_zones.mp4")
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

        draw_zones(frame, camera_zones)

        for det in by_frame.get(frame_idx, []):
            x1, y1, x2, y2 = int(det["x1"]), int(det["y1"]), int(det["x2"]), int(det["y2"])
            track_id = int(det["track_id"])
            color = color_for_track(track_id)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            fx, fy = foot_point(x1, y1, x2, y2)
            cv2.circle(frame, (int(fx), int(fy)), 5, (0, 0, 255), -1)
            cv2.putText(
                frame,
                f"id={track_id}",
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
