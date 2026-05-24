from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

# Espaço opcional entre data e hora (OCR frequentemente cola ano + hora).
TIMESTAMP_PATTERN = re.compile(
    r"(\d{2})[/.-](\d{2})[/.-](\d{4})\s*(\d{2}):(\d{2}):(\d{2})"
)

TESSERACT_INSTALL_HINT = (
    "Instale o Tesseract OCR e garanta que está no PATH:\n"
    "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
    "  Linux:   sudo apt install tesseract-ocr"
)


@dataclass
class OcrRoi:
    x: int
    y: int
    width: int
    height: int

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y : self.y + self.height, self.x : self.x + self.width]


def ensure_tesseract_available() -> None:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise RuntimeError(
            f"Tesseract OCR não está disponível. {TESSERACT_INSTALL_HINT}"
        ) from exc


def preprocess_roi(roi: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def normalize_ocr_timestamp_text(text: str) -> str:
    """Corrige leituras comuns do Tesseract antes do parse."""
    cleaned = text.replace("\n", " ").strip()
    # Ano colado na hora: 202606:16:30 -> 2026 06:16:30
    cleaned = re.sub(
        r"(\d{2}[/.-]\d{2}[/.-]\d{4})(\d{2}:\d{2}:\d{2})",
        r"\1 \2",
        cleaned,
    )
    return cleaned


def parse_timestamp_text(text: str) -> datetime | None:
    cleaned = normalize_ocr_timestamp_text(text)
    match = TIMESTAMP_PATTERN.search(cleaned)
    if not match:
        return None
    day, month, year, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
        )
    except ValueError:
        return None


def extract_timestamp_from_frame(
    frame: np.ndarray,
    roi: OcrRoi,
) -> tuple[datetime | None, str, float]:
    import pytesseract

    cropped = roi.crop(frame)
    processed = preprocess_roi(cropped)

    config = (
        r"--oem 3 --psm 7 "
        r"-c tessedit_char_whitelist=0123456789/:.- "
    )
    raw_text = pytesseract.image_to_string(processed, config=config)
    parsed = parse_timestamp_text(raw_text)
    confidence = 0.9 if parsed else 0.0
    return parsed, raw_text.strip(), confidence
