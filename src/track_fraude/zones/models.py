from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _polygons_equal(
    left: list[list[float]],
    right: list[list[float]],
) -> bool:
    if len(left) != len(right):
        return False
    return all(
        abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) < 0.01
        for a, b in zip(left, right)
    )


@dataclass(frozen=True)
class ZonePolygon:
    zone_id: str
    polygon: list[list[float]]
    lane_id: int | None = None
    label: str | None = None
    entry_vector: list[float] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZonePolygon:
        entry_vector = None
        if data.get("entry_vector") is not None:
            vector = data["entry_vector"]
            entry_vector = [float(vector[0]), float(vector[1])]
        return cls(
            zone_id=str(data["zone_id"]),
            polygon=[[float(x), float(y)] for x, y in data["polygon"]],
            lane_id=int(data["lane_id"]) if data.get("lane_id") is not None else None,
            label=str(data["label"]) if data.get("label") else None,
            entry_vector=entry_vector,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "zone_id": self.zone_id,
            "polygon": self.polygon,
        }
        if self.lane_id is not None:
            payload["lane_id"] = self.lane_id
        if self.label:
            payload["label"] = self.label
        if self.entry_vector is not None:
            payload["entry_vector"] = self.entry_vector
        return payload


@dataclass
class CameraZones:
    camera_id: str
    checkout_lanes: list[ZonePolygon] = field(default_factory=list)
    portal: ZonePolygon | None = None
    entrance: ZonePolygon | None = None
    exit: ZonePolygon | None = None

    @classmethod
    def from_dict(cls, camera_id: str, data: dict[str, Any]) -> CameraZones:
        checkout_lanes = [
            ZonePolygon.from_dict(item) for item in data.get("checkout_lanes", [])
        ]
        portal = ZonePolygon.from_dict(data["portal"]) if data.get("portal") else None
        entrance = (
            ZonePolygon.from_dict(data["entrance"]) if data.get("entrance") else None
        )
        exit_zone = ZonePolygon.from_dict(data["exit"]) if data.get("exit") else None

        if portal is None and entrance is not None and exit_zone is not None:
            if _polygons_equal(entrance.polygon, exit_zone.polygon):
                portal = entrance

        return cls(
            camera_id=camera_id,
            checkout_lanes=checkout_lanes,
            portal=portal,
            entrance=entrance,
            exit=exit_zone,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.checkout_lanes:
            payload["checkout_lanes"] = [lane.to_dict() for lane in self.checkout_lanes]
        if self.portal:
            payload["portal"] = self.portal.to_dict()
        if self.entrance and self.portal is None:
            payload["entrance"] = self.entrance.to_dict()
        if self.exit and self.portal is None:
            payload["exit"] = self.exit.to_dict()
        return payload


@dataclass
class ZonesConfig:
    store_id: str
    group_code: str
    cameras: dict[str, CameraZones]
    hysteresis_sec: float = 3.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZonesConfig:
        cameras = {
            camera_id: CameraZones.from_dict(camera_id, camera_data)
            for camera_id, camera_data in data.get("cameras", {}).items()
        }
        return cls(
            store_id=str(data["store_id"]),
            group_code=str(data.get("group_code") or "default"),
            cameras=cameras,
            hysteresis_sec=float(data.get("hysteresis_sec", 3.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "group_code": self.group_code,
            "hysteresis_sec": self.hysteresis_sec,
            "cameras": {
                camera_id: camera_zones.to_dict()
                for camera_id, camera_zones in sorted(self.cameras.items())
            },
        }

    def camera(self, camera_id: str) -> CameraZones:
        if camera_id not in self.cameras:
            raise KeyError(f"Zonas não definidas para câmera {camera_id!r}")
        return self.cameras[camera_id]
