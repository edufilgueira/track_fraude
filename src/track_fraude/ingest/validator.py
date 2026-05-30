from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_fraude.evidence.video_source import (
    _files_from_camera_entry,
    load_raw_day_manifest,
)
from track_fraude.pos.factory import create_pos_client
from track_fraude.storage import RawScope, raw_root
from track_fraude.video_paths import resolve_video_path


@dataclass
class IngestIssue:
    level: str  # error | warning
    code: str
    message: str


@dataclass
class IngestReport:
    date: str
    store_id: str
    group_code: str
    raw_day_dir: str
    cameras: dict[str, Any] = field(default_factory=dict)
    pos: dict[str, Any] = field(default_factory=dict)
    issues: list[IngestIssue] = field(default_factory=list)
    ok: bool = True

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(IngestIssue(level=level, code=code, message=message))
        if level == "error":
            self.ok = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "store_id": self.store_id,
            "group_code": self.group_code,
            "raw_day_dir": self.raw_day_dir,
            "ok": self.ok,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "cameras": self.cameras,
            "pos": self.pos,
            "issues": [
                {"level": item.level, "code": item.code, "message": item.message}
                for item in self.issues
            ],
        }


def _camera_video_paths(
    *,
    project_root: Path,
    raw_day_dir: Path,
    date: str,
    camera_id: str,
    store_id: str,
    group_code: str,
    manifest: dict[str, Any] | None,
) -> list[Path]:
    if manifest:
        cameras = manifest.get("cameras")
        if isinstance(cameras, list):
            for entry in cameras:
                if str(entry.get("camera_id")) == camera_id:
                    segments = _files_from_camera_entry(entry, raw_day_dir=raw_day_dir)
                    if segments:
                        return [segment.path for segment in segments]
        elif isinstance(cameras, dict) and camera_id in cameras:
            segments = _files_from_camera_entry(cameras[camera_id], raw_day_dir=raw_day_dir)
            if segments:
                return [segment.path for segment in segments]

    default_path = resolve_video_path(
        project_root,
        date=date,
        camera_id=camera_id,
        store_id=store_id,
        group_code=group_code,
        video=None,
    )
    return [default_path]


def validate_day_ingest(
    *,
    project_root: Path,
    date: str,
    store_id: str,
    group_code: str,
    camera_ids: list[str],
    pos_root: Path | str,
    pos_api_url: str | None = None,
) -> IngestReport:
    scope = RawScope.from_config(
        raw_root(project_root),
        {"group_code": group_code, "store_id": store_id},
    )
    raw_day_dir = scope.date_dir(date)
    report = IngestReport(
        date=date,
        store_id=store_id,
        group_code=group_code,
        raw_day_dir=str(raw_day_dir.as_posix()),
    )

    if not raw_day_dir.is_dir():
        report.add(
            "error",
            "raw_dir_missing",
            f"Pasta de vídeo não encontrada: {raw_day_dir}",
        )
        return report

    manifest = load_raw_day_manifest(raw_day_dir)
    if manifest is not None:
        report.cameras["manifest"] = str((raw_day_dir / "manifest.json").as_posix())

    for camera_id in sorted(camera_ids):
        paths = _camera_video_paths(
            project_root=project_root,
            raw_day_dir=raw_day_dir,
            date=date,
            camera_id=camera_id,
            store_id=store_id,
            group_code=group_code,
            manifest=manifest,
        )
        existing = [path for path in paths if path.is_file()]
        camera_info: dict[str, Any] = {
            "expected_paths": [str(path.as_posix()) for path in paths],
            "found_paths": [str(path.as_posix()) for path in existing],
        }
        if not existing:
            report.add(
                "error",
                "video_missing",
                f"Nenhum vídeo encontrado para {camera_id} em {date}",
            )
        report.cameras[camera_id] = camera_info

    try:
        if pos_api_url:
            pos_client = create_pos_client(pos_root=pos_root, pos_api_url=pos_api_url)
        else:
            pos_client = create_pos_client(pos_root=pos_root)
        export = pos_client.get_day_export(store_id, date)
        report.pos = {
            "source": "api" if pos_api_url else "file",
            "transaction_count": len(export.transactions),
        }
        if not export.transactions:
            report.add(
                "warning",
                "pos_empty",
                f"POS do dia {date} não tem transações (alertas R1/R3 podem ser limitados)",
            )
    except FileNotFoundError as exc:
        report.add("warning", "pos_missing", str(exc))
    except ValueError as exc:
        report.add("error", "pos_invalid", str(exc))

    return report


def save_ingest_report(path: Path, report: IngestReport) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, indent=2, ensure_ascii=False)
    return path
