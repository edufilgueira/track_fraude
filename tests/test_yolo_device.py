from __future__ import annotations

import track_fraude.yolo_device as yolo_device


def test_resolve_yolo_device_cpu_override(monkeypatch) -> None:
    monkeypatch.setenv("TRACK_FRAUDE_YOLO_DEVICE", "cpu")
    assert yolo_device.resolve_yolo_device() == "cpu"


def test_resolve_yolo_device_cuda_index_override(monkeypatch) -> None:
    monkeypatch.setenv("TRACK_FRAUDE_YOLO_DEVICE", "1")
    assert yolo_device.resolve_yolo_device() == 1
