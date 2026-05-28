from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def bbox_area(row: dict[str, Any]) -> float:
    width = max(0.0, float(row["x2"]) - float(row["x1"]))
    height = max(0.0, float(row["y2"]) - float(row["y1"]))
    return width * height


def _bbox_width_height(row: dict[str, Any]) -> tuple[float, float]:
    width = max(0.0, float(row["x2"]) - float(row["x1"]))
    height = max(0.0, float(row["y2"]) - float(row["y1"]))
    return width, height


def rows_near_time(
    rows: list[dict[str, Any]],
    target: datetime,
    *,
    window_sec: float = 2.0,
) -> list[dict[str, Any]]:
    delta = timedelta(seconds=window_sec)
    return [
        row
        for row in rows
        if target - delta <= _parse_dt(row["t_abs"]) <= target + delta
    ]


def rows_before_time(
    rows: list[dict[str, Any]],
    target: datetime,
    *,
    start_sec_before: float = 10.0,
    end_sec_before: float = 2.0,
) -> list[dict[str, Any]]:
    """Frames estáveis dentro da loja, antes de cruzar o portal na saída."""
    t_start = target - timedelta(seconds=start_sec_before)
    t_end = target - timedelta(seconds=end_sec_before)
    return [row for row in rows if t_start <= _parse_dt(row["t_abs"]) <= t_end]


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


# Largura/altura elevada costuma indicar braços estendidos ou objeto nas mãos.
_ASPECT_CARRY_THRESHOLD = 0.38
_WIDTH_CARRY_RATIO = 1.10


def _carry_metrics_from_row(row: dict[str, Any]) -> dict[str, float]:
    width, height = _bbox_width_height(row)
    aspect = (width / height) if height > 0 else 0.0
    carry_score = min(1.0, max(0.0, (aspect - 0.28) / 0.35))
    return {
        "width": width,
        "height": height,
        "aspect": aspect,
        "carry_score": carry_score,
        "bbox_area": bbox_area(row),
    }


def _hand_objects_from_metrics(
    metrics: dict[str, float],
    *,
    reference_width: float | None = None,
) -> int:
    aspect = metrics["aspect"]
    width = metrics["width"]
    if aspect >= _ASPECT_CARRY_THRESHOLD:
        return 1
    if reference_width and reference_width > 0:
        if width >= reference_width * _WIDTH_CARRY_RATIO:
            return 1
    if metrics["carry_score"] >= 0.55:
        return 1
    return 0


def _aggregate_carry_snapshot(
    rows: list[dict[str, Any]],
    *,
    reference_width: float | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    metrics_list = [_carry_metrics_from_row(row) for row in rows]
    width = _mean([item["width"] for item in metrics_list])
    aspect = _mean([item["aspect"] for item in metrics_list])
    carry_score = _mean([item["carry_score"] for item in metrics_list])
    area = _mean([item["bbox_area"] for item in metrics_list])
    ref = reference_width if reference_width is not None else width
    hand_objects = 1 if any(
        _hand_objects_from_metrics(item, reference_width=ref) > 0 for item in metrics_list
    ) else 0
    if hand_objects == 0 and carry_score >= 0.55:
        hand_objects = 1
    hands_empty = hand_objects == 0 and carry_score < 0.35
    bag = aspect >= 0.52 and hand_objects > 0
    return {
        "hands_empty": hands_empty,
        "hand_objects_bbox": hand_objects,
        "hand_objects": hand_objects,
        "bag": bag,
        "carry_score": round(carry_score, 3),
        "aspect": round(aspect, 3),
        "bbox_width": round(width, 1),
        "bbox_area": round(area, 1),
    }


def _merge_yolo_into_snapshot(
    snap: dict[str, Any] | None,
    yolo: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if snap is None:
        return None
    result = dict(snap)
    result.setdefault("hand_objects_bbox", int(result.get("hand_objects", 0)))

    if yolo is None:
        result["hand_objects_yolo"] = None
        result["hand_objects"] = int(result["hand_objects_bbox"])
        return result

    yolo_count = int(yolo.get("count", 0))
    result["hand_objects_yolo"] = yolo_count
    labels = list(yolo.get("labels") or [])
    if labels:
        result["yolo_labels"] = labels
    if yolo.get("frame_idx") is not None:
        result["yolo_frame_idx"] = int(yolo["frame_idx"])

    bbox_obj = int(result["hand_objects_bbox"])
    result["hand_objects"] = max(bbox_obj, yolo_count)
    result["hands_empty"] = (
        bbox_obj == 0
        and yolo_count == 0
        and float(result.get("carry_score", 0.0)) < 0.35
    )
    if yolo_count > 0 and result.get("bag") is not True:
        result["bag"] = any(
            label in {"handbag", "backpack", "suitcase"} for label in labels
        )
    return result


@dataclass(frozen=True)
class CarryProfile:
    carry_at_enter: dict[str, Any]
    carry_at_exit: dict[str, Any]
    confidence: float
    source: str

    @property
    def bag_at_enter(self) -> bool:
        return bool(self.carry_at_enter.get("bag"))

    @property
    def bag_at_exit(self) -> bool:
        return bool(self.carry_at_exit.get("bag"))

    @property
    def visual_estimate(self) -> int:
        enter_objects = int(self.carry_at_enter.get("hand_objects", 0))
        exit_objects = int(self.carry_at_exit.get("hand_objects", 0))
        enter_bag = 1 if self.bag_at_enter else 0
        exit_bag = 1 if self.bag_at_exit else 0
        delta = self.carry_delta()
        return max(
            enter_objects + enter_bag,
            exit_objects + exit_bag,
            int(delta.get("net_objects", 0)) + enter_objects + enter_bag,
        )

    def carry_delta(
        self,
        *,
        net_score_threshold: float = 0.15,
    ) -> dict[str, Any]:
        enter_bbox = int(
            self.carry_at_enter.get(
                "hand_objects_bbox",
                self.carry_at_enter.get("hand_objects", 0),
            )
        )
        exit_bbox = int(
            self.carry_at_exit.get(
                "hand_objects_bbox",
                self.carry_at_exit.get("hand_objects", 0),
            )
        )
        enter_yolo = self.carry_at_enter.get("hand_objects_yolo")
        exit_yolo = self.carry_at_exit.get("hand_objects_yolo")
        yolo_available = enter_yolo is not None and exit_yolo is not None

        enter_objects = int(self.carry_at_enter.get("hand_objects", enter_bbox))
        exit_objects = int(self.carry_at_exit.get("hand_objects", exit_bbox))
        enter_score = float(self.carry_at_enter.get("carry_score", 0.0))
        exit_score = float(self.carry_at_exit.get("carry_score", 0.0))
        net_objects_bbox = max(0, exit_bbox - enter_bbox)
        net_objects_yolo = (
            max(0, int(exit_yolo) - int(enter_yolo)) if yolo_available else None
        )
        net_objects = (
            int(net_objects_yolo)
            if yolo_available
            else max(0, exit_objects - enter_objects)
        )
        net_score = max(0.0, exit_score - enter_score)
        new_bag = self.bag_at_exit and not self.bag_at_enter
        enter_empty = bool(
            self.carry_at_enter.get(
                "hands_empty",
                enter_objects == 0 and enter_score < 0.35,
            )
        )
        exit_empty = bool(
            self.carry_at_exit.get(
                "hands_empty",
                exit_objects == 0 and exit_score < 0.35,
            )
        )

        if yolo_available:
            # YOLO prioritário; bbox só reforça quando YOLO também vê objeto na saída.
            net_carry = (
                int(net_objects_yolo) > 0
                or new_bag
                or (
                    enter_empty
                    and int(exit_yolo) > 0
                    and net_score >= net_score_threshold
                )
            )
            if int(enter_yolo) == 0 and int(exit_yolo) == 0:
                net_carry = False
            positive = net_carry and not (enter_empty and exit_empty)
        else:
            net_carry = net_objects_bbox > 0 or new_bag or (
                enter_empty and not exit_empty and net_score >= net_score_threshold
            )
            positive = net_carry and not (enter_empty and exit_empty)

        return {
            "net_objects": net_objects,
            "net_objects_bbox": net_objects_bbox,
            "net_objects_yolo": net_objects_yolo,
            "yolo_available": yolo_available,
            "net_score": round(net_score, 3),
            "new_bag": new_bag,
            "enter_empty": enter_empty,
            "exit_empty": exit_empty,
            "net_carry": net_carry,
            "positive": positive,
            "added_objects": net_objects,
            "volume_increase": False,
        }

    def has_net_carry_theft(
        self,
        *,
        net_score_threshold: float = 0.15,
        confidence_threshold: float = 0.55,
    ) -> bool:
        if self.confidence < confidence_threshold:
            return False
        return bool(
            self.carry_delta(net_score_threshold=net_score_threshold)["positive"]
        )

    def has_carry_increase(
        self,
        *,
        area_ratio_threshold: float = 1.25,
        confidence_threshold: float = 0.55,
    ) -> bool:
        """Compatibilidade — delega para delta líquido."""
        _ = area_ratio_threshold
        return self.has_net_carry_theft(confidence_threshold=confidence_threshold)

    def to_dict(self) -> dict[str, Any]:
        delta = self.carry_delta()
        return {
            "carry_at_enter": self.carry_at_enter,
            "carry_at_exit": self.carry_at_exit,
            "carry_baseline": dict(self.carry_at_enter),
            "carry_delta": delta,
            "confidence": round(self.confidence, 3),
            "visual_estimate": self.visual_estimate,
            "source": self.source,
        }


def compute_carry_profile(
    *,
    store_timeline: list[dict[str, Any]],
    track_rows: list[dict[str, Any]] | None = None,
    preset: dict[str, Any] | None = None,
    yolo_at_enter: dict[str, Any] | None = None,
    yolo_at_exit: dict[str, Any] | None = None,
    area_ratio_threshold: float = 1.25,
    exit_snapshot_start_before_sec: float = 10.0,
    exit_snapshot_end_before_sec: float = 2.0,
) -> CarryProfile | None:
    _ = area_ratio_threshold
    if preset:
        enter = dict(preset.get("carry_at_enter") or preset.get("carry_baseline") or {})
        exit_snap = dict(preset.get("carry_at_exit") or {})
        confidence = float(preset.get("confidence", 0.0))
        return CarryProfile(
            carry_at_enter=enter,
            carry_at_exit=exit_snap,
            confidence=confidence,
            source=str(preset.get("source", "preset")),
        )

    if not store_timeline or not track_rows:
        return None

    entered = next((e for e in store_timeline if e.get("event") == "entered"), None)
    left = next((e for e in store_timeline if e.get("event") == "left"), None)
    if entered is None or left is None:
        return None

    enter_rows = rows_near_time(track_rows, _parse_dt(entered["t"]))
    exit_rows = rows_before_time(
        track_rows,
        _parse_dt(left["t"]),
        start_sec_before=exit_snapshot_start_before_sec,
        end_sec_before=exit_snapshot_end_before_sec,
    )
    if not exit_rows:
        exit_rows = rows_near_time(track_rows, _parse_dt(left["t"]), window_sec=2.0)

    enter_snap = _aggregate_carry_snapshot(enter_rows)
    if enter_snap is None:
        return None
    exit_snap = _aggregate_carry_snapshot(
        exit_rows,
        reference_width=float(enter_snap.get("bbox_width", 0.0)),
    )
    if exit_snap is None:
        return None

    enter_snap = _merge_yolo_into_snapshot(enter_snap, yolo_at_enter)
    exit_snap = _merge_yolo_into_snapshot(exit_snap, yolo_at_exit)
    assert enter_snap is not None and exit_snap is not None

    yolo_used = yolo_at_enter is not None or yolo_at_exit is not None
    source = "bbox+yolo" if yolo_used else "hand_proxy"

    delta = CarryProfile(
        carry_at_enter=enter_snap,
        carry_at_exit=exit_snap,
        confidence=0.0,
        source=source,
    ).carry_delta()
    confidence = min(
        0.95,
        0.5 + float(delta["net_objects"]) * 0.15 + float(delta["net_score"]) * 0.4,
    )
    if delta["positive"]:
        confidence = max(confidence, 0.58)
    if delta.get("yolo_available") and int(delta.get("net_objects_yolo") or 0) > 0:
        confidence = max(confidence, 0.68)
    if (
        delta.get("yolo_available")
        and int(delta.get("net_objects_yolo") or 0) == 0
        and int(delta.get("net_objects_bbox") or 0) > 0
    ):
        confidence = min(confidence, 0.45)

    return CarryProfile(
        carry_at_enter=enter_snap,
        carry_at_exit=exit_snap,
        confidence=confidence,
        source=source,
    )
