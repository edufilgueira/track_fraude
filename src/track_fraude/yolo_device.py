from __future__ import annotations

import os
from typing import Literal

YoloDevice = int | Literal["cpu"]


def resolve_yolo_device() -> YoloDevice:
    """Device para inferência Ultralytics (CUDA quando PyTorch enxerga GPU)."""
    override = os.getenv("TRACK_FRAUDE_YOLO_DEVICE", "").strip()
    if override:
        if override.lower() == "cpu":
            return "cpu"
        return int(override)

    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return 0
    return "cpu"
