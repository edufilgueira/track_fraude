from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from track_fraude_core.db.connection import DEFAULT_DB_PATH, get_connection, init_database


@dataclass(frozen=True)
class PipelineRunRecord:
    id: int
    store_db_id: int
    date: str
    status: str
    current_phase: str
    current_camera: str | None
    started_at: str
    updated_at: str
    finished_at: str | None
    store_id: str | None = None
    group_db_id: int | None = None
    group_code: str | None = None


class PipelineRunRepository:
    STALE_AFTER = timedelta(hours=4)

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        init_database(self.db_path)

    def _conn(self):
        return get_connection(self.db_path)

    def cleanup_stale_runs(self) -> int:
        cutoff = (datetime.now(timezone.utc) - self.STALE_AFTER).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE pipeline_runs
                SET status = 'failed',
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE status = 'running' AND updated_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount

    def start_run(self, store_db_id: int, date: str) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_runs (
                    store_db_id, date, status, current_phase, started_at, updated_at
                ) VALUES (?, ?, 'running', 'ingest', datetime('now'), datetime('now'))
                """,
                (store_db_id, date),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_run(
        self,
        run_id: int,
        *,
        current_phase: str,
        current_camera: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET current_phase = ?,
                    current_camera = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'running'
                """,
                (current_phase, current_camera, run_id),
            )
            conn.commit()

    def finish_run(self, run_id: int, *, ok: bool) -> None:
        status = "completed" if ok else "failed"
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, run_id),
            )
            conn.commit()

    def _row_to_record(self, row) -> PipelineRunRecord:
        keys = set(row.keys())
        return PipelineRunRecord(
            id=int(row["id"]),
            store_db_id=int(row["store_db_id"]),
            date=str(row["date"]),
            status=str(row["status"]),
            current_phase=str(row["current_phase"] or ""),
            current_camera=str(row["current_camera"]) if row["current_camera"] else None,
            started_at=str(row["started_at"]),
            updated_at=str(row["updated_at"]),
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
            store_id=str(row["store_id"]) if "store_id" in keys else None,
            group_db_id=int(row["group_db_id"]) if "group_db_id" in keys else None,
            group_code=str(row["group_code"]) if "group_code" in keys else None,
        )

    def list_running(self) -> list[PipelineRunRecord]:
        self.cleanup_stale_runs()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT r.*, s.store_id, s.group_db_id, g.group_code
                FROM pipeline_runs r
                JOIN stores s ON s.id = r.store_db_id
                JOIN groups g ON g.id = s.group_db_id
                WHERE r.status = 'running'
                ORDER BY r.started_at ASC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def is_store_running(self, store_db_id: int) -> bool:
        return any(run.store_db_id == store_db_id for run in self.list_running())

    def is_group_running(self, group_db_id: int) -> bool:
        return any(run.group_db_id == group_db_id for run in self.list_running())
