from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from track_fraude.zones.models import ZonesConfig


def load_zones_config(path: Path | str) -> ZonesConfig:
    """Carrega zonas de um JSON (uso avançado: `--zones` ou import pontual)."""
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    if "cameras" not in payload and "checkout_lanes" in payload:
        payload = {
            "store_id": payload.get("store_id", "UNKNOWN"),
            "group_code": payload.get("group_code", "default"),
            "hysteresis_sec": payload.get("hysteresis_sec", 3.0),
            "cameras": {"cam2": payload},
        }

    return ZonesConfig.from_dict(payload)


def load_zones_for_store_config(config: dict[str, Any]) -> ZonesConfig | None:
    payload = config.get("zones") or {}
    if not payload.get("cameras"):
        return None
    merged = {
        "store_id": config.get("store_id", payload.get("store_id", "UNKNOWN")),
        "group_code": config.get("group_code", payload.get("group_code", "default")),
        "hysteresis_sec": payload.get("hysteresis_sec", 3.0),
        "cameras": payload["cameras"],
    }
    return ZonesConfig.from_dict(merged)


def resolve_zones_for_job(
    *,
    config: dict[str, Any],
    project_root: Path | str,
    zones_path: Path | str | None = None,
) -> ZonesConfig:
    if zones_path is not None:
        return load_zones_config(zones_path)

    from_sqlite = load_zones_for_store_config(config)
    if from_sqlite is not None:
        return from_sqlite

    raise FileNotFoundError(
        "Zonas não configuradas. Defina polígonos no painel web "
        "(Editar câmera → Definir zona no vídeo)."
    )
