from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from track_fraude_core.db.store_repository import StoreRecord

PROCESSED_DIR = Path("data/processed")


def _store_processed_dir(
    project_root: Path, *, group_code: str, store_id: str
) -> Path:
    return project_root / PROCESSED_DIR / group_code / store_id


def review_index_path(
    project_root: Path, *, group_code: str, store_id: str, date: str
) -> Path:
    return _store_processed_dir(
        project_root, group_code=group_code, store_id=store_id
    ) / date / "review" / "index.json"


def review_alert_dir(
    project_root: Path,
    *,
    group_code: str,
    store_id: str,
    date: str,
    alert_id: str,
) -> Path:
    return _store_processed_dir(
        project_root, group_code=group_code, store_id=store_id
    ) / date / "review" / alert_id


def list_review_dates(
    project_root: Path, store: StoreRecord, *, group_code: str
) -> list[str]:
    store_dir = _store_processed_dir(
        project_root, group_code=group_code, store_id=store.store_id
    )
    if not store_dir.is_dir():
        return []

    dates: list[str] = []
    for date_dir in store_dir.iterdir():
        if not date_dir.is_dir():
            continue
        if (date_dir / "review" / "index.json").is_file():
            dates.append(date_dir.name)
    return sorted(dates, reverse=True)


def has_review_evidence(
    project_root: Path, store: StoreRecord, *, group_code: str
) -> bool:
    return bool(list_review_dates(project_root, store, group_code=group_code))


def load_review_index(
    project_root: Path,
    store: StoreRecord,
    *,
    group_code: str,
    date: str,
) -> dict[str, Any]:
    path = review_index_path(
        project_root,
        group_code=group_code,
        store_id=store.store_id,
        date=date,
    )
    if not path.is_file():
        raise FileNotFoundError(f"Índice de revisão não encontrado: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_alert_from_index(
    review_index: dict[str, Any], alert_id: str
) -> dict[str, Any] | None:
    for alert in review_index.get("alerts") or []:
        if str(alert.get("alert_id")) == alert_id:
            return alert
    return None


def safe_review_media_path(
    project_root: Path,
    store: StoreRecord,
    *,
    group_code: str,
    date: str,
    alert_id: str,
    filename: str,
) -> Path:
    alert_dir = review_alert_dir(
        project_root,
        group_code=group_code,
        store_id=store.store_id,
        date=date,
        alert_id=alert_id,
    ).resolve()
    media_path = (alert_dir / filename).resolve()
    try:
        media_path.relative_to(alert_dir)
    except ValueError as exc:
        raise ValueError("Caminho de mídia inválido") from exc
    if not media_path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {filename}")
    return media_path


def list_alert_media_files(alert: dict[str, Any]) -> list[str]:
    files = alert.get("evidence_files") or []
    return [name for name in files if str(name).endswith(".mp4")]
