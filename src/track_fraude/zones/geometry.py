from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np


def foot_point(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Ponto de referência: centro inferior da bbox (pés da pessoa)."""
    return ((x1 + x2) / 2.0, y2)


def point_in_polygon(
    x: float,
    y: float,
    polygon: Sequence[Sequence[float]],
) -> bool:
    if len(polygon) < 3:
        return False
    pts = np.array(polygon, dtype=np.float32)
    return cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0
