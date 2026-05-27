from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


def appearance_histogram_from_crop(frame: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
    h, w = frame.shape[:2]
    ix1 = max(0, min(w - 1, int(round(x1))))
    iy1 = max(0, min(h - 1, int(round(y1))))
    ix2 = max(ix1 + 1, min(w, int(round(x2))))
    iy2 = max(iy1 + 1, min(h, int(round(y2))))
    crop = frame[iy1:iy2, ix1:ix2]
    if crop.size == 0:
        return np.zeros((180, 1), dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist.astype(np.float32)


def compare_appearances(left: np.ndarray, right: np.ndarray) -> float:
    score = float(cv2.compareHist(left, right, cv2.HISTCMP_CORREL))
    if score < 0:
        return 0.0
    return score


def extract_track_appearances(
    video_path: Path,
    rows_by_track: dict[int, list[dict[str, Any]]],
) -> dict[int, np.ndarray]:
    if not video_path.exists() or not rows_by_track:
        return {}

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return {}

    appearances: dict[int, np.ndarray] = {}
    try:
        for track_id, rows in rows_by_track.items():
            if not rows:
                continue
            sample = rows[len(rows) // 2]
            frame_idx = int(sample["frame_idx"])
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = capture.read()
            if not ok:
                continue
            appearances[track_id] = appearance_histogram_from_crop(
                frame,
                float(sample["x1"]),
                float(sample["y1"]),
                float(sample["x2"]),
                float(sample["y2"]),
            )
    finally:
        capture.release()

    return appearances
