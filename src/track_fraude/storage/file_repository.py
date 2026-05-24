from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_fraude.storage.base import (
    PipelineStateRepository,
    SyncMapRepository,
    TrackRepository,
)
from track_fraude.storage.paths import ProcessedScope


class FileTrackRepository(TrackRepository):
    def __init__(self, scope: ProcessedScope) -> None:
        self.scope = scope

    def save_tracks(self, camera_id: str, date: str, tracks: list[dict[str, Any]]) -> Path:
        path = self.scope.tracks_path(date, camera_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(tracks, handle, indent=2, ensure_ascii=False)
        return path

    def load_tracks(self, camera_id: str, date: str) -> list[dict[str, Any]]:
        path = self.scope.tracks_path(date, camera_id)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)


class FileSyncMapRepository(SyncMapRepository):
    def __init__(self, scope: ProcessedScope) -> None:
        self.scope = scope

    def save(self, camera_id: str, date: str, payload: dict[str, Any]) -> Path:
        path = self.scope.sync_map_path(date, camera_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return path

    def load(self, camera_id: str, date: str) -> dict[str, Any]:
        path = self.scope.sync_map_path(date, camera_id)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)


class FilePipelineStateRepository(PipelineStateRepository):
    def __init__(self, scope: ProcessedScope) -> None:
        self.scope = scope

    def default_state(self, date: str, camera_ids: list[str]) -> dict[str, Any]:
        return {
            "date": date,
            "group_code": self.scope.group_code,
            "store_id": self.scope.store_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "phases": {
                "sync": {"status": "pending"},
                "track": {"status": "pending"},
                "merge": {"status": "pending"},
                "events": {"status": "pending"},
                "pos_match": {"status": "pending"},
                "alerts": {"status": "pending"},
                "evidence": {"status": "pending"},
            },
            "cameras": {
                camera_id: {"sync": "pending", "track": "pending"}
                for camera_id in sorted(camera_ids)
            },
        }

    @staticmethod
    def merge_camera_entries(
        state: dict[str, Any], camera_ids: list[str]
    ) -> dict[str, Any]:
        cameras = state.setdefault("cameras", {})
        for camera_id in camera_ids:
            if camera_id not in cameras:
                cameras[camera_id] = {"sync": "pending", "track": "pending"}
        return state

    def load(self, date: str) -> dict[str, Any]:
        path = self.scope.pipeline_state_path(date)
        if not path.exists():
            raise FileNotFoundError(f"pipeline_state não encontrado: {path}")
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, date: str, state: dict[str, Any]) -> Path:
        path = self.scope.pipeline_state_path(date)
        path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["group_code"] = self.scope.group_code
        state["store_id"] = self.scope.store_id
        with path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
        return path

    def init_if_missing(self, date: str, camera_ids: list[str]) -> dict[str, Any]:
        path = self.scope.pipeline_state_path(date)
        if path.exists():
            state = self.load(date)
            return self.merge_camera_entries(state, camera_ids)
        state = self.default_state(date, camera_ids)
        self.save(date, state)
        return state
