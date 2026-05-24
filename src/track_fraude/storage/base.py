from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class TrackRepository(ABC):
    @abstractmethod
    def save_tracks(self, camera_id: str, date: str, tracks: list[dict[str, Any]]) -> Path:
        raise NotImplementedError

    @abstractmethod
    def load_tracks(self, camera_id: str, date: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class SyncMapRepository(ABC):
    @abstractmethod
    def save(self, camera_id: str, date: str, payload: dict[str, Any]) -> Path:
        raise NotImplementedError

    @abstractmethod
    def load(self, camera_id: str, date: str) -> dict[str, Any]:
        raise NotImplementedError


class PipelineStateRepository(ABC):
    @abstractmethod
    def load(self, date: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save(self, date: str, state: dict[str, Any]) -> Path:
        raise NotImplementedError
