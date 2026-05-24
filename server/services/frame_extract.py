from __future__ import annotations

from pathlib import Path


def extract_frame_jpeg(video_path: Path, seconds: float = 0.0) -> tuple[bytes, int, int, float]:
    """Extrai um frame do vídeo e retorna JPEG + dimensões + duração em segundos."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Não foi possível abrir o vídeo: {video_path.name}")

    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_sec = (total_frames / fps) if fps > 0 and total_frames > 0 else 0.0

        if fps > 0 and duration_sec > 0:
            seconds = max(0.0, min(float(seconds), max(0.0, duration_sec - 0.05)))
            frame_idx = int(seconds * fps)
            if total_frames > 0:
                frame_idx = max(0, min(frame_idx, total_frames - 1))
        else:
            frame_idx = max(0, int(seconds))

        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
        if not ok or frame is None:
            raise ValueError("Não foi possível ler frame do vídeo")

        height, width = frame.shape[:2]
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise ValueError("Falha ao codificar frame")
        return encoded.tobytes(), width, height, duration_sec
    finally:
        capture.release()
