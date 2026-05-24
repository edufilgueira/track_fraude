from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SyncSample:
    frame_idx: int
    t_abs: datetime
    confidence: float
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_idx": self.frame_idx,
            "t_abs": self.t_abs.isoformat(),
            "confidence": self.confidence,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncSample:
        return cls(
            frame_idx=int(data["frame_idx"]),
            t_abs=datetime.fromisoformat(str(data["t_abs"])),
            confidence=float(data.get("confidence", 1.0)),
            raw_text=str(data.get("raw_text", "")),
        )


@dataclass
class SyncAnchor:
    frame_idx: int
    t_abs: datetime
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_idx": self.frame_idx,
            "t_abs": self.t_abs.isoformat(),
            "source": self.source,
        }


@dataclass
class SyncMap:
    camera_id: str
    date: str
    video_path: str
    fps: float
    frame_count: int
    timezone: str
    anchor: SyncAnchor
    samples: list[SyncSample] = field(default_factory=list)
    build_method: str = "ocr+interpolation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "date": self.date,
            "video_path": self.video_path,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "timezone": self.timezone,
            "build_method": self.build_method,
            "anchor": self.anchor.to_dict(),
            "samples": [sample.to_dict() for sample in self.samples],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncMap:
        anchor_data = data["anchor"]
        return cls(
            camera_id=str(data["camera_id"]),
            date=str(data["date"]),
            video_path=str(data["video_path"]),
            fps=float(data["fps"]),
            frame_count=int(data["frame_count"]),
            timezone=str(data["timezone"]),
            anchor=SyncAnchor(
                frame_idx=int(anchor_data["frame_idx"]),
                t_abs=datetime.fromisoformat(str(anchor_data["t_abs"])),
                source=str(anchor_data.get("source", "unknown")),
            ),
            samples=[SyncSample.from_dict(s) for s in data.get("samples", [])],
            build_method=str(data.get("build_method", "ocr+interpolation")),
        )

    def timestamp_at_frame(self, frame_idx: int) -> datetime:
        from datetime import timedelta

        delta_sec = (frame_idx - self.anchor.frame_idx) / self.fps
        return self.anchor.t_abs + timedelta(seconds=delta_sec)

    def frame_at_timestamp(self, target: datetime) -> int:
        from datetime import timedelta

        delta_sec = (target - self.anchor.t_abs).total_seconds()
        return int(round(self.anchor.frame_idx + delta_sec * self.fps))
