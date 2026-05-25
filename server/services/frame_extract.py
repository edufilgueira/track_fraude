from __future__ import annotations

from pathlib import Path


def _is_mostly_black(frame, *, threshold: float = 12.0) -> bool:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) < threshold


def _read_frame_at_seconds(capture, seconds: float, fps: float, total_frames: int):
    import cv2

    if fps > 0:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    elif total_frames > 0:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(seconds)))

    ok, frame = capture.read()
    if ok and frame is not None:
        return frame

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ok, frame = capture.read()
    return frame if ok and frame is not None else None


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

        seconds = max(0.0, float(seconds))
        if duration_sec > 0:
            seconds = min(seconds, max(0.0, duration_sec - 0.05))

        candidate_seconds = [seconds]
        if seconds < 2.0:
            candidate_seconds.extend([1.0, 2.0, 5.0, 10.0, 30.0])
        else:
            candidate_seconds.extend([max(0.0, seconds - 1.0), seconds + 1.0])

        seen: set[float] = set()
        frame = None
        for candidate in candidate_seconds:
            if candidate in seen:
                continue
            seen.add(candidate)
            if duration_sec > 0 and candidate > duration_sec:
                continue
            candidate_frame = _read_frame_at_seconds(capture, candidate, fps, total_frames)
            if candidate_frame is None:
                continue
            if _is_mostly_black(candidate_frame) and candidate != candidate_seconds[-1]:
                continue
            frame = candidate_frame
            break

        if frame is None:
            raise ValueError(
                "Não foi possível ler frame do vídeo (arquivo vazio, codec não suportado ou frames pretos)."
            )

        height, width = frame.shape[:2]
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise ValueError("Falha ao codificar frame")
        return encoded.tobytes(), width, height, duration_sec
    finally:
        capture.release()
