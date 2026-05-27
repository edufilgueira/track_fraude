from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from track_fraude.models.sync import SyncMap


@dataclass(frozen=True)
class VideoSegment:
    path: Path
    t_start: datetime
    t_end: datetime | None = None


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _probe_duration_sec(video_path: Path) -> float:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return 0.0
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps > 0 and frames > 0:
            return frames / fps
    finally:
        capture.release()
    return 0.0


def _finalize_segment_ends(segments: list[VideoSegment]) -> list[VideoSegment]:
    if not segments:
        return segments
    ordered = sorted(segments, key=lambda item: item.t_start)
    finalized: list[VideoSegment] = []
    for index, segment in enumerate(ordered):
        if index + 1 < len(ordered):
            t_end = ordered[index + 1].t_start
        else:
            duration = _probe_duration_sec(segment.path)
            t_end = segment.t_start + timedelta(seconds=max(duration, 1.0))
        finalized.append(VideoSegment(segment.path, segment.t_start, t_end))
    return finalized


def _files_from_camera_entry(
    entry: dict[str, Any] | list[Any], *, raw_day_dir: Path
) -> list[VideoSegment]:
    files = entry.get("files") if isinstance(entry, dict) else entry
    if not isinstance(files, list):
        return []
    segments: list[VideoSegment] = []
    for item in files:
        if not isinstance(item, dict) or "path" not in item or "t_start" not in item:
            continue
        path = raw_day_dir / str(item["path"])
        segments.append(VideoSegment(path=path, t_start=_parse_dt(item["t_start"])))
    return _finalize_segment_ends(segments)


def load_raw_day_manifest(raw_day_dir: Path) -> dict[str, Any] | None:
    manifest_path = raw_day_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    with manifest_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_video_segments(
    *,
    project_root: Path,
    date: str,
    camera_id: str,
    sync_map: SyncMap | None,
    processed_manifest_path: Path | None,
) -> list[VideoSegment]:
    raw_day_dir = project_root / "data" / "raw" / "video" / date
    manifest = load_raw_day_manifest(raw_day_dir)
    if manifest:
        cameras = manifest.get("cameras")
        if isinstance(cameras, list):
            for entry in cameras:
                if str(entry.get("camera_id")) == camera_id:
                    segments = _files_from_camera_entry(entry, raw_day_dir=raw_day_dir)
                    if segments:
                        return segments
        elif isinstance(cameras, dict) and camera_id in cameras:
            segments = _files_from_camera_entry(cameras[camera_id], raw_day_dir=raw_day_dir)
            if segments:
                return segments

    video_path: Path | None = None
    t_start: datetime | None = None

    if processed_manifest_path and processed_manifest_path.is_file():
        payload = json.loads(processed_manifest_path.read_text(encoding="utf-8"))
        if payload.get("video_path"):
            video_path = Path(str(payload["video_path"]))

    if sync_map is not None:
        if video_path is None:
            video_path = Path(sync_map.video_path)
        t_start = sync_map.anchor.t_abs

    if video_path is None:
        candidate = raw_day_dir / f"{camera_id}.mp4"
        if candidate.is_file():
            video_path = candidate
            if sync_map is not None:
                t_start = sync_map.anchor.t_abs

    if video_path is None or not video_path.is_file():
        raise FileNotFoundError(
            f"Vídeo não encontrado para {camera_id} em {date}. "
            f"Verifique data/raw/video/{date}/ ou manifest.json."
        )

    if t_start is None:
        t_start = datetime.fromisoformat(f"{date}T00:00:00")

    duration = _probe_duration_sec(video_path)
    return [
        VideoSegment(
            path=video_path,
            t_start=t_start,
            t_end=t_start + timedelta(seconds=max(duration, 1.0)),
        )
    ]


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
    )


def _extract_segment_clip(
    segment: VideoSegment,
    *,
    clip_start: datetime,
    clip_end: datetime,
    output_path: Path,
) -> None:
    seg_end = segment.t_end or segment.t_start
    local_start = max(0.0, (clip_start - segment.t_start).total_seconds())
    local_end = min(
        (seg_end - segment.t_start).total_seconds(),
        (clip_end - segment.t_start).total_seconds(),
    )
    duration = max(0.1, local_end - local_start)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{local_start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(segment.path),
            "-c",
            "copy",
            str(output_path),
        ]
    )


def extract_clip_for_range(
    segments: list[VideoSegment],
    *,
    clip_start: datetime,
    clip_end: datetime,
    output_path: Path,
) -> None:
    if clip_end <= clip_start:
        raise ValueError("Intervalo de clip inválido")

    overlapping = [
        segment
        for segment in segments
        if (segment.t_end or segment.t_start) > clip_start and segment.t_start < clip_end
    ]
    if not overlapping:
        raise FileNotFoundError("Nenhum segmento de vídeo cobre o intervalo solicitado")

    if len(overlapping) == 1:
        _extract_segment_clip(
            overlapping[0],
            clip_start=clip_start,
            clip_end=clip_end,
            output_path=output_path,
        )
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        part_paths: list[Path] = []
        for index, segment in enumerate(overlapping):
            part_path = tmp / f"part_{index:03d}.mp4"
            _extract_segment_clip(
                segment,
                clip_start=clip_start,
                clip_end=clip_end,
                output_path=part_path,
            )
            part_paths.append(part_path)

        if len(part_paths) == 1:
            shutil.copy2(part_paths[0], output_path)
            return

        list_file = tmp / "concat.txt"
        lines = "\n".join(f"file '{path.as_posix()}'" for path in part_paths)
        list_file.write_text(lines, encoding="utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ]
        )
