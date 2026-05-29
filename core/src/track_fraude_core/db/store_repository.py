from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from track_fraude_core.db.camera_roles import (
    CAMERA_ROLE_SUPPORT,
    infer_camera_role,
    normalize_camera_role,
)
from track_fraude_core.db.alert_rule_defaults import (
    BUFFER_AFTER_SEC,
    BUFFER_BEFORE_SEC,
    CARRY_CONFIDENCE_THRESHOLD,
    CHECKOUT_BUFFER_AFTER_SEC,
    CHECKOUT_BUFFER_BEFORE_SEC,
    ENABLE_R4,
    POS_MATCH_DELTA_SEC,
    R1_MIN_CHECKOUT_DURATION_SEC,
    R3_VISUAL_MARGIN,
    R4_FAST_DURATION_SEC,
    R4_MIN_ITEMS,
    R5_CANCELLED_DELTA_SEC,
    T_RETURN_SEC,
    VID_STRIDE,
)
from track_fraude_core.db.connection import DEFAULT_DB_PATH, get_connection, init_database


@dataclass
class StoreRecord:
    id: int
    group_db_id: int
    store_id: str
    name: str
    street: str
    number: str
    neighborhood: str
    city: str
    state: str
    cep: str
    timezone: str
    ocr_sample_interval_sec: int
    ocr_min_confidence: float
    pos_match_delta_sec: int
    r1_min_checkout_duration_sec: float
    t_return_sec: float
    r3_visual_margin: int
    carry_confidence_threshold: float
    r4_min_items: int
    r4_fast_duration_sec: float
    enable_r4: bool
    r5_cancelled_delta_sec: int
    buffer_before_sec: float
    buffer_after_sec: float
    checkout_buffer_before_sec: float
    checkout_buffer_after_sec: float
    vid_stride: int
    active: bool


@dataclass
class CameraRecord:
    id: int
    store_db_id: int
    camera_id: str
    description: str
    camera_role: str
    ocr_x: int
    ocr_y: int
    ocr_width: int
    ocr_height: int


@dataclass
class CameraZoneRecord:
    id: int
    camera_db_id: int
    zone_type: str
    zone_id: str
    label: str
    lane_id: int | None
    polygon: list[list[float]]
    entry_vector: list[float] | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "zone_id": self.zone_id,
            "zone_type": self.zone_type,
            "label": self.label,
            "polygon": self.polygon,
        }
        if self.lane_id is not None:
            payload["lane_id"] = self.lane_id
        if self.entry_vector is not None:
            payload["entry_vector"] = self.entry_vector
        return payload


class StoreRepository:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        init_database(self.db_path)

    def _conn(self):
        return get_connection(self.db_path)

    @staticmethod
    def _store_from_row(row: Any) -> StoreRecord:
        keys = row.keys()
        return StoreRecord(
            id=int(row["id"]),
            group_db_id=int(row["group_db_id"]),
            store_id=str(row["store_id"]),
            name=str(row["name"]),
            street=str(row["street"] or ""),
            number=str(row["number"] or ""),
            neighborhood=str(row["neighborhood"] or ""),
            city=str(row["city"] or ""),
            state=str(row["state"] or ""),
            cep=str(row["cep"] or ""),
            timezone=str(row["timezone"]),
            ocr_sample_interval_sec=int(row["ocr_sample_interval_sec"]),
            ocr_min_confidence=float(row["ocr_min_confidence"]),
            pos_match_delta_sec=int(row["pos_match_delta_sec"]),
            r1_min_checkout_duration_sec=float(row["r1_min_checkout_duration_sec"]),
            t_return_sec=float(row["t_return_sec"]) if "t_return_sec" in keys else T_RETURN_SEC,
            r3_visual_margin=int(row["r3_visual_margin"]) if "r3_visual_margin" in keys else R3_VISUAL_MARGIN,
            carry_confidence_threshold=float(row["carry_confidence_threshold"])
            if "carry_confidence_threshold" in keys
            else CARRY_CONFIDENCE_THRESHOLD,
            r4_min_items=int(row["r4_min_items"]) if "r4_min_items" in keys else R4_MIN_ITEMS,
            r4_fast_duration_sec=float(row["r4_fast_duration_sec"])
            if "r4_fast_duration_sec" in keys
            else R4_FAST_DURATION_SEC,
            enable_r4=bool(row["enable_r4"]) if "enable_r4" in keys else ENABLE_R4,
            r5_cancelled_delta_sec=int(row["r5_cancelled_delta_sec"])
            if "r5_cancelled_delta_sec" in keys
            else R5_CANCELLED_DELTA_SEC,
            buffer_before_sec=float(row["buffer_before_sec"])
            if "buffer_before_sec" in keys
            else BUFFER_BEFORE_SEC,
            buffer_after_sec=float(row["buffer_after_sec"])
            if "buffer_after_sec" in keys
            else BUFFER_AFTER_SEC,
            checkout_buffer_before_sec=float(row["checkout_buffer_before_sec"])
            if "checkout_buffer_before_sec" in keys
            else CHECKOUT_BUFFER_BEFORE_SEC,
            checkout_buffer_after_sec=float(row["checkout_buffer_after_sec"])
            if "checkout_buffer_after_sec" in keys
            else CHECKOUT_BUFFER_AFTER_SEC,
            vid_stride=int(row["vid_stride"]) if "vid_stride" in keys else VID_STRIDE,
            active=bool(row["active"]),
        )

    @staticmethod
    def _camera_from_row(row: Any) -> CameraRecord:
        role = str(row["camera_role"] if "camera_role" in row.keys() else CAMERA_ROLE_SUPPORT)
        return CameraRecord(
            id=int(row["id"]),
            store_db_id=int(row["store_db_id"]),
            camera_id=str(row["camera_id"]),
            description=str(row["description"] or ""),
            camera_role=role,
            ocr_x=int(row["ocr_x"]),
            ocr_y=int(row["ocr_y"]),
            ocr_width=int(row["ocr_width"]),
            ocr_height=int(row["ocr_height"]),
        )

    @staticmethod
    def _zone_from_row(row: Any) -> CameraZoneRecord:
        polygon = json.loads(str(row["polygon_json"]))
        entry_vector_raw = row["entry_vector_json"]
        entry_vector = (
            json.loads(str(entry_vector_raw))
            if entry_vector_raw not in (None, "")
            else None
        )
        lane_id = row["lane_id"]
        return CameraZoneRecord(
            id=int(row["id"]),
            camera_db_id=int(row["camera_db_id"]),
            zone_type=str(row["zone_type"]),
            zone_id=str(row["zone_id"]),
            label=str(row["label"] or ""),
            lane_id=int(lane_id) if lane_id is not None else None,
            polygon=[[float(x), float(y)] for x, y in polygon],
            entry_vector=[float(v) for v in entry_vector] if entry_vector else None,
        )

    def list_stores(
        self,
        *,
        group_db_id: int | None = None,
        active_only: bool = False,
    ) -> list[StoreRecord]:
        query = "SELECT * FROM stores WHERE 1=1"
        params: list[Any] = []
        if group_db_id is not None:
            query += " AND group_db_id = ?"
            params.append(group_db_id)
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY name"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._store_from_row(row) for row in rows]

    def get_store(self, db_id: int) -> StoreRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM stores WHERE id = ?", (db_id,)).fetchone()
        return self._store_from_row(row) if row else None

    def get_store_by_code(
        self,
        store_id: str,
        *,
        group_db_id: int | None = None,
        group_code: str | None = None,
    ) -> StoreRecord | None:
        query = "SELECT stores.* FROM stores"
        params: list[Any] = [store_id.strip()]
        if group_code:
            query += " JOIN groups ON groups.id = stores.group_db_id"
            query += " WHERE stores.store_id = ? AND groups.group_code = ?"
            params.append(group_code.strip())
        elif group_db_id is not None:
            query += " WHERE stores.store_id = ? AND stores.group_db_id = ?"
            params.append(group_db_id)
        else:
            query += " WHERE stores.store_id = ?"

        with self._conn() as conn:
            row = conn.execute(query, params).fetchone()
        return self._store_from_row(row) if row else None

    def list_stores_by_code(self, store_id: str) -> list[StoreRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM stores WHERE store_id = ? ORDER BY name",
                (store_id.strip(),),
            ).fetchall()
        return [self._store_from_row(row) for row in rows]

    def create_store(
        self,
        *,
        group_db_id: int,
        store_id: str,
        name: str,
        street: str = "",
        number: str = "",
        neighborhood: str = "",
        city: str = "",
        state: str = "",
        cep: str = "",
        timezone: str = "America/Sao_Paulo",
        ocr_sample_interval_sec: int = 30,
        ocr_min_confidence: float = 0.5,
        pos_match_delta_sec: int = POS_MATCH_DELTA_SEC,
        r1_min_checkout_duration_sec: float = R1_MIN_CHECKOUT_DURATION_SEC,
        t_return_sec: float = T_RETURN_SEC,
        r3_visual_margin: int = R3_VISUAL_MARGIN,
        carry_confidence_threshold: float = CARRY_CONFIDENCE_THRESHOLD,
        r4_min_items: int = R4_MIN_ITEMS,
        r4_fast_duration_sec: float = R4_FAST_DURATION_SEC,
        enable_r4: bool = ENABLE_R4,
        r5_cancelled_delta_sec: int = R5_CANCELLED_DELTA_SEC,
        buffer_before_sec: float = BUFFER_BEFORE_SEC,
        buffer_after_sec: float = BUFFER_AFTER_SEC,
        checkout_buffer_before_sec: float = CHECKOUT_BUFFER_BEFORE_SEC,
        checkout_buffer_after_sec: float = CHECKOUT_BUFFER_AFTER_SEC,
        vid_stride: int = VID_STRIDE,
        active: bool = True,
    ) -> StoreRecord:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stores (
                    group_db_id, store_id, name,
                    street, number, neighborhood, city, state, cep,
                    timezone, ocr_sample_interval_sec, ocr_min_confidence,
                    pos_match_delta_sec, r1_min_checkout_duration_sec,
                    t_return_sec, r3_visual_margin, carry_confidence_threshold,
                    r4_min_items, r4_fast_duration_sec, enable_r4,
                    r5_cancelled_delta_sec,
                    buffer_before_sec, buffer_after_sec,
                    checkout_buffer_before_sec, checkout_buffer_after_sec,
                    vid_stride,
                    active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_db_id,
                    store_id.strip(),
                    name.strip(),
                    street.strip(),
                    number.strip(),
                    neighborhood.strip(),
                    city.strip(),
                    state.strip().upper()[:2],
                    cep.strip(),
                    timezone.strip(),
                    ocr_sample_interval_sec,
                    ocr_min_confidence,
                    pos_match_delta_sec,
                    float(r1_min_checkout_duration_sec),
                    float(t_return_sec),
                    r3_visual_margin,
                    carry_confidence_threshold,
                    r4_min_items,
                    float(r4_fast_duration_sec),
                    1 if enable_r4 else 0,
                    r5_cancelled_delta_sec,
                    float(buffer_before_sec),
                    float(buffer_after_sec),
                    float(checkout_buffer_before_sec),
                    float(checkout_buffer_after_sec),
                    int(vid_stride),
                    1 if active else 0,
                ),
            )
            conn.commit()
            db_id = int(cursor.lastrowid)
        store = self.get_store(db_id)
        assert store is not None
        return store

    def update_store(self, db_id: int, **fields: Any) -> StoreRecord | None:
        allowed = {
            "group_db_id",
            "store_id",
            "name",
            "street",
            "number",
            "neighborhood",
            "city",
            "state",
            "cep",
            "timezone",
            "ocr_sample_interval_sec",
            "ocr_min_confidence",
            "pos_match_delta_sec",
            "r1_min_checkout_duration_sec",
            "t_return_sec",
            "r3_visual_margin",
            "carry_confidence_threshold",
            "r4_min_items",
            "r4_fast_duration_sec",
            "enable_r4",
            "r5_cancelled_delta_sec",
            "buffer_before_sec",
            "buffer_after_sec",
            "checkout_buffer_before_sec",
            "checkout_buffer_after_sec",
            "vid_stride",
            "active",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_store(db_id)

        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0
        if "enable_r4" in updates:
            updates["enable_r4"] = 1 if updates["enable_r4"] else 0
        for text_field in ("store_id", "name", "street", "number", "neighborhood", "city", "cep", "timezone"):
            if text_field in updates:
                updates[text_field] = str(updates[text_field]).strip()
        if "state" in updates:
            updates["state"] = str(updates["state"]).strip().upper()[:2]

        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [db_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE stores SET {columns}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            conn.commit()
        return self.get_store(db_id)

    def delete_store(self, db_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM stores WHERE id = ?", (db_id,))
            conn.commit()

    def list_cameras(self, store_db_id: int) -> list[CameraRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cameras WHERE store_db_id = ? ORDER BY camera_id",
                (store_db_id,),
            ).fetchall()
        return [self._camera_from_row(row) for row in rows]

    def get_camera(self, camera_db_id: int) -> CameraRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM cameras WHERE id = ?", (camera_db_id,)
            ).fetchone()
        return self._camera_from_row(row) if row else None

    def create_camera(
        self,
        *,
        store_db_id: int,
        camera_id: str,
        description: str = "",
        camera_role: str | None = None,
        ocr_x: int = 10,
        ocr_y: int = 10,
        ocr_width: int = 420,
        ocr_height: int = 50,
    ) -> CameraRecord:
        role = normalize_camera_role(
            camera_role
            or infer_camera_role(camera_id=camera_id.strip(), description=description)
        )
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cameras (
                    store_db_id, camera_id, description, camera_role,
                    ocr_x, ocr_y, ocr_width, ocr_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store_db_id,
                    camera_id.strip(),
                    description.strip(),
                    role,
                    ocr_x,
                    ocr_y,
                    ocr_width,
                    ocr_height,
                ),
            )
            conn.commit()
            cam_id = int(cursor.lastrowid)
        camera = self.get_camera(cam_id)
        assert camera is not None
        return camera

    def update_camera(self, camera_db_id: int, **fields: Any) -> CameraRecord | None:
        allowed = {
            "camera_id",
            "description",
            "camera_role",
            "ocr_x",
            "ocr_y",
            "ocr_width",
            "ocr_height",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_camera(camera_db_id)

        if "camera_role" in updates:
            updates["camera_role"] = normalize_camera_role(str(updates["camera_role"]))
        if "camera_id" in updates:
            updates["camera_id"] = str(updates["camera_id"]).strip()
        if "description" in updates:
            updates["description"] = str(updates["description"]).strip()

        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [camera_db_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE cameras SET {columns}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            conn.commit()
        return self.get_camera(camera_db_id)

    def delete_camera(self, camera_db_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cameras WHERE id = ?", (camera_db_id,))
            conn.commit()

    def list_camera_zones(self, camera_db_id: int) -> list[CameraZoneRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM camera_zones
                WHERE camera_db_id = ?
                ORDER BY sort_order, zone_id
                """,
                (camera_db_id,),
            ).fetchall()
        return [self._zone_from_row(row) for row in rows]

    def get_camera_zone(self, zone_db_id: int) -> CameraZoneRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM camera_zones WHERE id = ?",
                (zone_db_id,),
            ).fetchone()
        return self._zone_from_row(row) if row else None

    def save_camera_zone(
        self,
        *,
        camera_db_id: int,
        zone_type: str,
        zone_id: str,
        polygon: list[list[float]],
        label: str = "",
        lane_id: int | None = None,
        entry_vector: list[float] | None = None,
        sort_order: int = 0,
    ) -> CameraZoneRecord:
        if len(polygon) < 3:
            raise ValueError("Polígono precisa de pelo menos 3 pontos")

        payload_polygon = json.dumps(
            [[float(x), float(y)] for x, y in polygon],
            ensure_ascii=False,
        )
        payload_vector = (
            json.dumps([float(entry_vector[0]), float(entry_vector[1])])
            if entry_vector is not None
            else None
        )

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO camera_zones (
                    camera_db_id, zone_type, zone_id, label, lane_id,
                    polygon_json, entry_vector_json, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(camera_db_id, zone_id) DO UPDATE SET
                    zone_type = excluded.zone_type,
                    label = excluded.label,
                    lane_id = excluded.lane_id,
                    polygon_json = excluded.polygon_json,
                    entry_vector_json = excluded.entry_vector_json,
                    sort_order = excluded.sort_order,
                    updated_at = datetime('now')
                """,
                (
                    camera_db_id,
                    zone_type.strip(),
                    zone_id.strip(),
                    label.strip(),
                    lane_id,
                    payload_polygon,
                    payload_vector,
                    sort_order,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT * FROM camera_zones
                WHERE camera_db_id = ? AND zone_id = ?
                """,
                (camera_db_id, zone_id.strip()),
            ).fetchone()
        assert row is not None
        return self._zone_from_row(row)

    def delete_camera_zone(self, camera_db_id: int, zone_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM camera_zones WHERE camera_db_id = ? AND zone_id = ?",
                (camera_db_id, zone_id.strip()),
            )
            conn.commit()

    def build_zones_payload(
        self,
        store: StoreRecord,
        *,
        group_code: str,
        hysteresis_sec: float = 3.0,
    ) -> dict[str, Any]:
        cameras_payload: dict[str, Any] = {}
        for camera in self.list_cameras(store.id):
            zones = self.list_camera_zones(camera.id)
            if not zones:
                continue
            camera_zones: dict[str, Any] = {}
            checkout_lanes: list[dict[str, Any]] = []
            for zone in zones:
                zone_dict = {
                    "zone_id": zone.zone_id,
                    "polygon": zone.polygon,
                }
                if zone.label:
                    zone_dict["label"] = zone.label
                if zone.entry_vector is not None:
                    zone_dict["entry_vector"] = zone.entry_vector

                if zone.zone_type == "portal":
                    camera_zones["portal"] = zone_dict
                elif zone.zone_type == "checkout_lane":
                    lane_dict = dict(zone_dict)
                    if zone.lane_id is not None:
                        lane_dict["lane_id"] = zone.lane_id
                    checkout_lanes.append(lane_dict)
                elif zone.zone_type == "entrance":
                    camera_zones["entrance"] = zone_dict
                elif zone.zone_type == "exit":
                    camera_zones["exit"] = zone_dict

            if checkout_lanes:
                checkout_lanes.sort(key=lambda item: item.get("lane_id") or 0)
                camera_zones["checkout_lanes"] = checkout_lanes
            if camera_zones:
                cameras_payload[camera.camera_id] = camera_zones

        return {
            "store_id": store.store_id,
            "group_code": group_code,
            "hysteresis_sec": hysteresis_sec,
            "cameras": cameras_payload,
        }

    def to_config_dict(self, store: StoreRecord, *, group_code: str | None = None) -> dict[str, Any]:
        cameras = self.list_cameras(store.id)
        if group_code is None:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT group_code FROM groups WHERE id = ?",
                    (store.group_db_id,),
                ).fetchone()
            group_code = str(row["group_code"]) if row else ""

        zones_payload = self.build_zones_payload(store, group_code=group_code)

        return {
            "group_code": group_code,
            "store_id": store.store_id,
            "timezone": store.timezone,
            "address": {
                "street": store.street,
                "number": store.number,
                "neighborhood": store.neighborhood,
                "city": store.city,
                "state": store.state,
                "cep": store.cep,
            },
            "cameras": {
                cam.camera_id: {
                    "description": cam.description,
                    "camera_role": cam.camera_role,
                    "ocr_roi": {
                        "x": cam.ocr_x,
                        "y": cam.ocr_y,
                        "width": cam.ocr_width,
                        "height": cam.ocr_height,
                    },
                }
                for cam in cameras
            },
            "zones": zones_payload,
            "sync": {
                "ocr_sample_interval_sec": store.ocr_sample_interval_sec,
                "ocr_min_confidence": store.ocr_min_confidence,
                "pos_match_delta_sec": store.pos_match_delta_sec,
                "r1_min_checkout_duration_sec": store.r1_min_checkout_duration_sec,
            },
            "alert_rules": {
                "t_return_sec": store.t_return_sec,
                "r3_visual_margin": store.r3_visual_margin,
                "carry_confidence_threshold": store.carry_confidence_threshold,
                "r4_min_items": store.r4_min_items,
                "r4_fast_duration_sec": store.r4_fast_duration_sec,
                "enable_r4": store.enable_r4,
                "r5_cancelled_delta_sec": store.r5_cancelled_delta_sec,
            },
            "evidence": {
                "buffer_before_sec": store.buffer_before_sec,
                "buffer_after_sec": store.buffer_after_sec,
                "checkout_buffer_before_sec": store.checkout_buffer_before_sec,
                "checkout_buffer_after_sec": store.checkout_buffer_after_sec,
            },
            "track": {
                "vid_stride": store.vid_stride,
            },
        }
