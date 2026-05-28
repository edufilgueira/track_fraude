from __future__ import annotations

from datetime import datetime
from pathlib import Path

from track_fraude.models.sync import SyncMap


def read_frame_at_timestamp(
    video_path: Path,
    sync_map: SyncMap,
    target: datetime,
):
    """Lê um frame BGR do vídeo no instante absoluto (via sync_map)."""
    import cv2

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Vídeo não encontrado: {path}")

    frame_idx = sync_map.frame_at_timestamp(target)
    frame_idx = max(0, min(frame_idx, max(0, sync_map.frame_count - 1)))

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {path}")
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Falha ao ler frame {frame_idx} de {path}")
        return frame, frame_idx
    finally:
        capture.release()
