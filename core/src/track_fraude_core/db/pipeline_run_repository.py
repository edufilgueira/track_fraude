from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from track_fraude_core.db.connection import get_connection, init_database
from track_fraude_core.db.database import DatabaseConfig, resolve_database
from track_fraude_core.pipeline_queue import (
    PIPELINE_ACTIVE_STATUSES,
    PIPELINE_STATUS_CANCELLED,
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_QUEUED,
    PIPELINE_STATUS_RUNNING,
)


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
    worker_node: str | None = None
    worker_id: str | None = None
    job_id: str | None = None
    log_path: str | None = None
    error_message: str | None = None
    store_id: str | None = None
    group_db_id: int | None = None
    group_code: str | None = None


class PipelineRunRepository:
    STALE_AFTER = timedelta(hours=4)
    CLEANUP_INTERVAL_SEC = 60.0

    def __init__(self, db: DatabaseConfig | Path | str | None = None) -> None:
        self.db = resolve_database(db)
        self._last_cleanup_at = 0.0
        init_database(self.db)

    def _conn(self):
        return get_connection(self.db)

    def cleanup_stale_runs(self) -> int:
        now = time.monotonic()
        if now - self._last_cleanup_at < self.CLEANUP_INTERVAL_SEC:
            return 0
        self._last_cleanup_at = now
        cutoff = (datetime.now(timezone.utc) - self.STALE_AFTER).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE status = 'running' AND updated_at < ?
                """,
                (PIPELINE_STATUS_FAILED, cutoff),
            )
            conn.commit()
            return cursor.rowcount

    def start_run(self, store_db_id: int, date: str) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_runs (
                    store_db_id, date, status, current_phase, started_at, updated_at
                ) VALUES (?, ?, ?, 'ingest', datetime('now'), datetime('now'))
                """,
                (store_db_id, date, PIPELINE_STATUS_RUNNING),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def enqueue_run(
        self,
        store_db_id: int,
        date: str,
        *,
        log_path: str | None = None,
        job_id: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_runs (
                    store_db_id, date, status, current_phase, log_path, job_id,
                    started_at, updated_at
                ) VALUES (?, ?, ?, '', ?, ?, datetime('now'), datetime('now'))
                """,
                (store_db_id, date, PIPELINE_STATUS_QUEUED, log_path, job_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def mark_run_running(
        self,
        run_id: int,
        *,
        worker_node: str | None = None,
        worker_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    current_phase = CASE
                        WHEN current_phase = '' THEN 'ingest'
                        ELSE current_phase
                    END,
                    worker_node = COALESCE(?, worker_node),
                    worker_id = COALESCE(?, worker_id),
                    job_id = COALESCE(?, job_id),
                    updated_at = datetime('now')
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    PIPELINE_STATUS_RUNNING,
                    worker_node,
                    worker_id,
                    job_id,
                    run_id,
                    PIPELINE_STATUS_QUEUED,
                    PIPELINE_STATUS_RUNNING,
                ),
            )
            conn.commit()

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
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    current_phase,
                    current_camera,
                    run_id,
                    PIPELINE_STATUS_QUEUED,
                    PIPELINE_STATUS_RUNNING,
                ),
            )
            conn.commit()

    def finish_run(
        self,
        run_id: int,
        *,
        ok: bool,
        error_message: str | None = None,
    ) -> None:
        status = PIPELINE_STATUS_COMPLETED if ok else PIPELINE_STATUS_FAILED
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    error_message = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ? AND status != ?
                """,
                (status, error_message, run_id, PIPELINE_STATUS_CANCELLED),
            )
            conn.commit()

    def cancel_run(self, run_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    finished_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    PIPELINE_STATUS_CANCELLED,
                    run_id,
                    PIPELINE_STATUS_QUEUED,
                    PIPELINE_STATUS_RUNNING,
                ),
            )
            conn.commit()

    def set_job_id(self, run_id: int, job_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET job_id = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (job_id.strip(), run_id),
            )
            conn.commit()

    def get_running_for_store(self, store_db_id: int) -> PipelineRunRecord | None:
        for run in self.list_running():
            if run.store_db_id == store_db_id:
                return run
        return None

    def get_run(self, run_id: int) -> PipelineRunRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT r.*, s.store_id, s.group_db_id, g.group_code
                FROM pipeline_runs r
                JOIN stores s ON s.id = r.store_db_id
                JOIN groups g ON g.id = s.group_db_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

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
            worker_node=str(row["worker_node"]) if "worker_node" in keys and row["worker_node"] else None,
            worker_id=str(row["worker_id"]) if "worker_id" in keys and row["worker_id"] else None,
            job_id=str(row["job_id"]) if "job_id" in keys and row["job_id"] else None,
            log_path=str(row["log_path"]) if "log_path" in keys and row["log_path"] else None,
            error_message=str(row["error_message"])
            if "error_message" in keys and row["error_message"]
            else None,
            store_id=str(row["store_id"]) if "store_id" in keys else None,
            group_db_id=int(row["group_db_id"]) if "group_db_id" in keys else None,
            group_code=str(row["group_code"]) if "group_code" in keys else None,
        )

    def list_running(self) -> list[PipelineRunRecord]:
        self.cleanup_stale_runs()
        placeholders = ", ".join("?" for _ in PIPELINE_ACTIVE_STATUSES)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT r.*, s.store_id, s.group_db_id, g.group_code
                FROM pipeline_runs r
                JOIN stores s ON s.id = r.store_db_id
                JOIN groups g ON g.id = s.group_db_id
                WHERE r.status IN ({placeholders})
                ORDER BY r.started_at ASC
                """,
                PIPELINE_ACTIVE_STATUSES,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def is_store_running(self, store_db_id: int) -> bool:
        return any(run.store_db_id == store_db_id for run in self.list_running())

    def is_group_running(self, group_db_id: int) -> bool:
        return any(run.group_db_id == group_db_id for run in self.list_running())
