from __future__ import annotations

from dataclasses import dataclass

DEFAULT_EVIDENCE_FFMPEG_PRESET = "fast"
DEFAULT_EVIDENCE_CRF = 28

FFMPEG_PRESET_CHOICES: tuple[str, ...] = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
)


@dataclass(frozen=True)
class EvidenceEncodeSettings:
    scale_width: int | None
    preset: str
    crf: int


def normalize_evidence_ffmpeg_preset(value: str | None) -> str:
    preset = str(value or DEFAULT_EVIDENCE_FFMPEG_PRESET).strip().lower()
    if preset not in FFMPEG_PRESET_CHOICES:
        raise ValueError(
            f"preset FFmpeg inválido: {value!r}. "
            f"Opções: {', '.join(FFMPEG_PRESET_CHOICES)}"
        )
    return preset


def normalize_evidence_crf(value: int | float | str | None) -> int:
    crf = int(value if value is not None else DEFAULT_EVIDENCE_CRF)
    if not (0 <= crf <= 51):
        raise ValueError("CRF inválido (0–51)")
    return crf


def normalize_evidence_scale_width(value: int | float | str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    width = int(text)
    if width <= 0:
        raise ValueError("scale inválido (use vazio ou largura > 0 em pixels)")
    if width > 7680:
        raise ValueError("scale inválido (máximo 7680 px)")
    return width


def evidence_encode_settings(
    *,
    scale_width: int | float | str | None,
    preset: str | None,
    crf: int | float | str | None,
) -> EvidenceEncodeSettings:
    return EvidenceEncodeSettings(
        scale_width=normalize_evidence_scale_width(scale_width),
        preset=normalize_evidence_ffmpeg_preset(preset),
        crf=normalize_evidence_crf(crf),
    )
