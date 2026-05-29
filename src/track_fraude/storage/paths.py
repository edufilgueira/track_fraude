from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROCESSED_DIR = Path("data/processed")
DEFAULT_OUTPUT_DIR = Path("data/output")


def processed_root(project_root: Path | str) -> Path:
    """Raiz dos artefatos intermediários (sync, tracks, pipeline_state)."""
    return Path(project_root) / DEFAULT_PROCESSED_DIR


def output_root(project_root: Path | str) -> Path:
    """Raiz dos entregáveis finais (alertas, clips, índices para revisão)."""
    return Path(project_root) / DEFAULT_OUTPUT_DIR


@dataclass(frozen=True)
class StoreScope:
    """Escopo de dados por grupo + loja (mesma hierarquia em processed e output)."""

    root: Path
    group_code: str
    store_id: str

    @classmethod
    def from_config(cls, root: Path | str, config: dict) -> StoreScope:
        group_code = str(config.get("group_code") or "default").strip() or "default"
        store_id = str(config["store_id"]).strip()
        return cls(root=Path(root), group_code=group_code, store_id=store_id)

    def date_dir(self, date: str) -> Path:
        return self.root / self.group_code / self.store_id / date


@dataclass(frozen=True)
class ProcessedScope(StoreScope):
    """Artefatos técnicos do pipeline em data/processed/."""

    def pipeline_state_path(self, date: str) -> Path:
        return self.date_dir(date) / "pipeline_state.json"

    def sync_map_path(self, date: str, camera_id: str) -> Path:
        return self.date_dir(date) / camera_id / "sync_map.json"

    def tracks_path(self, date: str, camera_id: str) -> Path:
        return self.date_dir(date) / camera_id / "tracks.parquet"

    def manifest_path(self, date: str, camera_id: str) -> Path:
        return self.date_dir(date) / camera_id / "manifest.json"

    def events_dir(self, date: str) -> Path:
        return self.date_dir(date) / "events"

    def timelines_path(self, date: str) -> Path:
        return self.events_dir(date) / "timelines.json"

    def alerts_dir(self, date: str) -> Path:
        return self.date_dir(date) / "alerts"

    def alerts_index_path(self, date: str) -> Path:
        return self.alerts_dir(date) / "index.json"

    def alert_dir(self, date: str, alert_id: str) -> Path:
        return self.alerts_dir(date) / alert_id

    def merge_dir(self, date: str) -> Path:
        return self.date_dir(date) / "merge"

    def persons_path(self, date: str) -> Path:
        return self.merge_dir(date) / "persons.json"

    def cross_camera_links_path(self, date: str) -> Path:
        return self.merge_dir(date) / "cross_camera_links.json"

    def review_dir(self, date: str) -> Path:
        return self.date_dir(date) / "review"

    def review_alert_dir(self, date: str, alert_id: str) -> Path:
        return self.review_dir(date) / alert_id

    def review_index_path(self, date: str) -> Path:
        return self.review_dir(date) / "index.json"


@dataclass(frozen=True)
class OutputScope(StoreScope):
    """Reservado para entregáveis futuros (ex.: exportação para revisão na Fase 8)."""
