from __future__ import annotations

from typing import Any


def sync_phase_status(state: dict[str, Any], camera_ids: list[str]) -> str:
    """Calcula status da fase sync com base nas câmeras cadastradas."""
    if not camera_ids:
        return "completed"

    statuses = [
        state.get("cameras", {}).get(cam, {}).get("sync", "pending")
        for cam in camera_ids
    ]
    if all(status == "completed" for status in statuses):
        return "completed"
    if any(status == "completed" for status in statuses):
        return "partial"
    return "pending"
