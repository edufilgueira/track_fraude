from __future__ import annotations

import json
from pathlib import Path

import cv2

from track_fraude.models.sync import SyncAnchor, SyncMap, SyncSample
from track_fraude.sync.ocr_timestamp import (
    OcrRoi,
    ensure_tesseract_available,
    extract_timestamp_from_frame,
)


def roi_from_config(camera_id: str, config: dict) -> OcrRoi:
    roi = config["cameras"][camera_id]["ocr_roi"]
    return OcrRoi(
        x=int(roi["x"]),
        y=int(roi["y"]),
        width=int(roi["width"]),
        height=int(roi["height"]),
    )


def build_sync_map(
    *,
    camera_id: str,
    date: str,
    video_path: Path,
    config: dict,
    sample_interval_sec: int | None = None,
) -> SyncMap:
    ensure_tesseract_available()

    timezone = config.get("timezone", "America/Sao_Paulo")
    interval = sample_interval_sec or int(
        config.get("sync", {}).get("ocr_sample_interval_sec", 30)
    )
    roi = roi_from_config(camera_id, config)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Não foi possível abrir o vídeo: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(fps * interval)))

    samples: list[SyncSample] = []
    anchor: SyncAnchor | None = None
    last_raw_text = ""

    frame_idx = 0
    while frame_idx < frame_count:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = capture.read()
        if not ok:
            break

        parsed, raw_text, confidence = extract_timestamp_from_frame(frame, roi)
        if raw_text:
            last_raw_text = raw_text
        if parsed is not None:
            sample = SyncSample(
                frame_idx=frame_idx,
                t_abs=parsed,
                confidence=confidence,
                raw_text=raw_text,
            )
            samples.append(sample)
            if anchor is None:
                anchor = SyncAnchor(
                    frame_idx=frame_idx,
                    t_abs=parsed,
                    source="ocr",
                )
        frame_idx += step

    capture.release()

    if anchor is None:
        hint = (
            f"Último texto OCR: {last_raw_text!r} (formato não reconhecido)."
            if last_raw_text
            else "Nenhum texto lido na ROI."
        )
        raise RuntimeError(
            "OCR (Tesseract) não encontrou timestamp válido no vídeo. "
            "Verifique a ROI OCR no painel web e se o relógio está visível no vídeo. "
            f"{hint}"
        )

    return SyncMap(
        camera_id=camera_id,
        date=date,
        video_path=str(video_path.as_posix()),
        fps=float(fps),
        frame_count=frame_count,
        timezone=timezone,
        anchor=anchor,
        samples=samples,
        build_method="ocr+interpolation",
    )


def save_sync_map(sync_map: SyncMap, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(sync_map.to_dict(), handle, indent=2, ensure_ascii=False)


def load_sync_map(path: Path | str) -> SyncMap:
    with Path(path).open(encoding="utf-8") as handle:
        return SyncMap.from_dict(json.load(handle))
