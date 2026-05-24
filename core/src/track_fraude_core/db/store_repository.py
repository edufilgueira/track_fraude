from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    active: bool


@dataclass
class CameraRecord:
    id: int
    store_db_id: int
    camera_id: str
    description: str
    ocr_x: int
    ocr_y: int
    ocr_width: int
    ocr_height: int


class StoreRepository:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        init_database(self.db_path)

    def _conn(self):
        return get_connection(self.db_path)

    @staticmethod
    def _store_from_row(row: Any) -> StoreRecord:
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
            active=bool(row["active"]),
        )

    @staticmethod
    def _camera_from_row(row: Any) -> CameraRecord:
        return CameraRecord(
            id=int(row["id"]),
            store_db_id=int(row["store_db_id"]),
            camera_id=str(row["camera_id"]),
            description=str(row["description"] or ""),
            ocr_x=int(row["ocr_x"]),
            ocr_y=int(row["ocr_y"]),
            ocr_width=int(row["ocr_width"]),
            ocr_height=int(row["ocr_height"]),
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
        pos_match_delta_sec: int = 60,
        active: bool = True,
    ) -> StoreRecord:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stores (
                    group_db_id, store_id, name,
                    street, number, neighborhood, city, state, cep,
                    timezone, ocr_sample_interval_sec, ocr_min_confidence,
                    pos_match_delta_sec, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            "active",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_store(db_id)

        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0
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
        ocr_x: int = 10,
        ocr_y: int = 10,
        ocr_width: int = 420,
        ocr_height: int = 50,
    ) -> CameraRecord:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cameras (
                    store_db_id, camera_id, description,
                    ocr_x, ocr_y, ocr_width, ocr_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store_db_id,
                    camera_id.strip(),
                    description.strip(),
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
            "ocr_x",
            "ocr_y",
            "ocr_width",
            "ocr_height",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_camera(camera_db_id)

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

    def to_config_dict(self, store: StoreRecord, *, group_code: str | None = None) -> dict[str, Any]:
        cameras = self.list_cameras(store.id)
        if group_code is None:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT group_code FROM groups WHERE id = ?",
                    (store.group_db_id,),
                ).fetchone()
            group_code = str(row["group_code"]) if row else ""

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
                    "ocr_roi": {
                        "x": cam.ocr_x,
                        "y": cam.ocr_y,
                        "width": cam.ocr_width,
                        "height": cam.ocr_height,
                    },
                }
                for cam in cameras
            },
            "sync": {
                "ocr_sample_interval_sec": store.ocr_sample_interval_sec,
                "ocr_min_confidence": store.ocr_min_confidence,
                "pos_match_delta_sec": store.pos_match_delta_sec,
            },
        }
