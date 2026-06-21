from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Classes COCO úteis para carga (mãos / sacolas / objetos leváveis)
CARRY_CLASS_IDS: dict[int, str] = {
    24: "backpack",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    41: "cup",
    67: "cell phone",
    73: "book",
}


def _require_ultralytics():
    try:
        from ultralytics import YOLO  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'Ultralytics não instalado. Execute: pip install -e ".[track]"'
        ) from exc


def _expand_bbox(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    margin_ratio: float = 0.25,
    frame_w: int | None = None,
    frame_h: int | None = None,
) -> tuple[int, int, int, int]:
    width = x2 - x1
    height = y2 - y1
    mx = width * margin_ratio
    my = height * margin_ratio
    ex1 = int(max(0, x1 - mx))
    ey1 = int(max(0, y1 - my))
    ex2 = int(x2 + mx)
    ey2 = int(y2 + my)
    if frame_w is not None:
        ex2 = min(frame_w, ex2)
    if frame_h is not None:
        ey2 = min(frame_h, ey2)
    return ex1, ey1, ex2, ey2


def _center_inside(box: tuple[float, float, float, float], region: tuple[int, int, int, int]) -> bool:
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0
    rx1, ry1, rx2, ry2 = region
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


@dataclass(frozen=True)
class CarryObjectDetection:
    count: int
    labels: list[str]
    confidences: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "labels": self.labels,
            "confidences": [round(value, 3) for value in self.confidences],
        }


def detect_carry_objects(
    frame,
    *,
    person_bbox: tuple[float, float, float, float] | None = None,
    model_name: str = "/app/models/yolov8n.pt",
    conf: float = 0.35,
) -> CarryObjectDetection:
    """Detecta objetos carregáveis com YOLO; opcionalmente filtra pela ROI da pessoa."""
    _require_ultralytics()
    from ultralytics import YOLO

    model = YOLO(model_name)
    height, width = frame.shape[:2]
    region = None
    if person_bbox is not None:
        region = _expand_bbox(
            *person_bbox,
            margin_ratio=0.30,
            frame_w=width,
            frame_h=height,
        )

    results = model.predict(
        frame,
        conf=conf,
        classes=list(CARRY_CLASS_IDS.keys()),
        verbose=False,
    )
    labels: list[str] = []
    confidences: list[float] = []

    if not results:
        return CarryObjectDetection(count=0, labels=[], confidences=[])

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return CarryObjectDetection(count=0, labels=[], confidences=[])

    xyxy = boxes.xyxy.cpu().numpy()
    cls_ids = boxes.cls.int().cpu().tolist()
    confs = boxes.conf.cpu().numpy().tolist()

    for box, cls_id, score in zip(xyxy, cls_ids, confs, strict=True):
        if region is not None and not _center_inside(tuple(box), region):
            continue
        label = CARRY_CLASS_IDS.get(int(cls_id), f"class_{cls_id}")
        labels.append(label)
        confidences.append(float(score))

    return CarryObjectDetection(
        count=len(labels),
        labels=labels,
        confidences=confidences,
    )
