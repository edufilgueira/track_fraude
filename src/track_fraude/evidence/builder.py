from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from track_fraude.evidence.summary import (
    build_pos_context,
    build_summary_text,
    build_timeline_payload,
)
from track_fraude.evidence.video_source import extract_clip_for_range, resolve_video_segments
from track_fraude.evidence.store_config import evidence_encode_settings_from_store
from track_fraude.evidence.window import (
    EvidenceWindow,
    compute_checkout_range,
    compute_evidence_range,
)
from track_fraude.merge.builder import resolve_merge_cameras
from track_fraude.models.sync import SyncMap
from track_fraude.storage import ProcessedScope


@dataclass(frozen=True)
class EvidencePackResult:
    alert_id: str
    output_dir: Path
    files: list[str]
    clip_start: datetime
    clip_end: datetime


def _load_sync_map(
    processed: ProcessedScope, *, date: str, camera_id: str
) -> SyncMap | None:
    path = processed.sync_map_path(date, camera_id)
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return SyncMap.from_dict(json.load(handle))


def build_evidence_pack(
    *,
    alert: dict[str, Any],
    date: str,
    project_root: Path,
    processed: ProcessedScope,
    config: dict[str, Any],
    window: EvidenceWindow,
    skip_clips: bool = False,
) -> EvidencePackResult:
    alert_id = str(alert["alert_id"])
    output_dir = processed.review_alert_dir(date, alert_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_start, clip_end = compute_evidence_range(alert, window=window)
    checkout_range = compute_checkout_range(alert, window=window)

    entrance_camera, checkout_camera = resolve_merge_cameras(config)

    written: list[str] = []

    timeline_path = output_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps(build_timeline_payload(alert), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    written.append(timeline_path.name)

    pos_path = output_dir / "pos_context.json"
    pos_path.write_text(
        json.dumps(build_pos_context(alert), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    written.append(pos_path.name)

    summary_path = output_dir / "summary.txt"
    summary_path.write_text(build_summary_text(alert), encoding="utf-8")
    written.append(summary_path.name)

    encode_settings = evidence_encode_settings_from_store(config)

    if not skip_clips:
        for camera_id in (entrance_camera, checkout_camera):
            sync_map = _load_sync_map(processed, date=date, camera_id=camera_id)
            segments = resolve_video_segments(
                project_root=project_root,
                date=date,
                camera_id=camera_id,
                sync_map=sync_map,
                processed_manifest_path=processed.manifest_path(date, camera_id),
            )
            clip_path = output_dir / f"{camera_id}_clip.mp4"
            extract_clip_for_range(
                segments,
                clip_start=clip_start,
                clip_end=clip_end,
                output_path=clip_path,
                web_compatible=True,
                encode_settings=encode_settings,
            )
            written.append(clip_path.name)

        if checkout_range is not None:
            checkout_start, checkout_end = checkout_range
            sync_map = _load_sync_map(processed, date=date, camera_id=checkout_camera)
            segments = resolve_video_segments(
                project_root=project_root,
                date=date,
                camera_id=checkout_camera,
                sync_map=sync_map,
                processed_manifest_path=processed.manifest_path(date, checkout_camera),
            )
            checkout_clip = output_dir / f"{checkout_camera}_checkout_clip.mp4"
            extract_clip_for_range(
                segments,
                clip_start=checkout_start,
                clip_end=checkout_end,
                output_path=checkout_clip,
                web_compatible=True,
                encode_settings=encode_settings,
            )
            written.append(checkout_clip.name)

    meta_path = output_dir / "evidence.json"
    meta = {
        "alert_id": alert_id,
        "clip_start": clip_start.isoformat(),
        "clip_end": clip_end.isoformat(),
        "entrance_camera": entrance_camera,
        "checkout_camera": checkout_camera,
        "files": written,
    }
    if checkout_range is not None:
        meta["checkout_clip_start"] = checkout_range[0].isoformat()
        meta["checkout_clip_end"] = checkout_range[1].isoformat()
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(meta_path.name)

    return EvidencePackResult(
        alert_id=alert_id,
        output_dir=output_dir,
        files=written,
        clip_start=clip_start,
        clip_end=clip_end,
    )


def build_review_index(
    *,
    alerts_index: dict[str, Any],
    packs: list[EvidencePackResult],
) -> dict[str, Any]:
    pack_by_id = {pack.alert_id: pack for pack in packs}
    enriched_alerts: list[dict[str, Any]] = []
    for alert in alerts_index.get("alerts", []):
        alert_id = str(alert.get("alert_id"))
        payload = dict(alert)
        pack = pack_by_id.get(alert_id)
        if pack is not None:
            payload["evidence_dir"] = pack.output_dir.as_posix()
            payload["evidence_files"] = pack.files
            payload["clip_start"] = pack.clip_start.isoformat()
            payload["clip_end"] = pack.clip_end.isoformat()
        enriched_alerts.append(payload)

    return {
        **alerts_index,
        "evidence_generated_at": datetime.now().isoformat(),
        "alert_count": len(enriched_alerts),
        "alerts": enriched_alerts,
    }
