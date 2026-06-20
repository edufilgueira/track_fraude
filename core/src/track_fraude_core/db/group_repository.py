from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from track_fraude_core.db.connection import get_connection, init_database
from track_fraude_core.db.database import DatabaseConfig, resolve_database


@dataclass
class GroupRecord:
    id: int
    group_code: str
    name: str
    active: bool


class GroupRepository:
    def __init__(self, db: DatabaseConfig | Path | str | None = None) -> None:
        self.db = resolve_database(db)
        init_database(self.db)

    def _conn(self):
        return get_connection(self.db)

    @staticmethod
    def _group_from_row(row: Any) -> GroupRecord:
        return GroupRecord(
            id=int(row["id"]),
            group_code=str(row["group_code"]),
            name=str(row["name"]),
            active=bool(row["active"]),
        )

    def list_groups(self, active_only: bool = False) -> list[GroupRecord]:
        query = "SELECT * FROM groups"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY name"
        with self._conn() as conn:
            rows = conn.execute(query).fetchall()
        return [self._group_from_row(row) for row in rows]

    def get_group(self, db_id: int) -> GroupRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM groups WHERE id = ?", (db_id,)).fetchone()
        return self._group_from_row(row) if row else None

    def get_group_by_code(self, group_code: str) -> GroupRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM groups WHERE group_code = ?",
                (group_code.strip(),),
            ).fetchone()
        return self._group_from_row(row) if row else None

    def create_group(
        self,
        *,
        group_code: str,
        name: str,
        active: bool = True,
    ) -> GroupRecord:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO groups (group_code, name, active)
                VALUES (?, ?, ?)
                """,
                (group_code.strip(), name.strip(), 1 if active else 0),
            )
            conn.commit()
            group_id = int(cursor.lastrowid)
        group = self.get_group(group_id)
        assert group is not None
        return group

    def update_group(self, db_id: int, **fields: Any) -> GroupRecord | None:
        allowed = {"group_code", "name", "active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_group(db_id)

        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0
        if "group_code" in updates:
            updates["group_code"] = str(updates["group_code"]).strip()
        if "name" in updates:
            updates["name"] = str(updates["name"]).strip()

        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [db_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE groups SET {columns}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            conn.commit()
        return self.get_group(db_id)

    def delete_group(self, db_id: int) -> None:
        with self._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS total FROM stores WHERE group_db_id = ?",
                (db_id,),
            ).fetchone()
            if count and int(count["total"]) > 0:
                raise ValueError("Grupo possui lojas cadastradas")
            conn.execute("DELETE FROM groups WHERE id = ?", (db_id,))
            conn.commit()

    def count_stores(self, group_db_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM stores WHERE group_db_id = ?",
                (group_db_id,),
            ).fetchone()
        return int(row["total"]) if row else 0
