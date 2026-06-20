from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from track_fraude_core.db.database import DatabaseConfig, resolve_database
from track_fraude_core.db.session import get_connection


@dataclass(frozen=True)
class WorkloadRecord:
    id: int
    slug: str
    name: str
    image: str
    queue_name: str
    k8s_namespace: str
    gpu_pool_slug: str | None
    active: bool
    config_json: dict[str, Any]


@dataclass(frozen=True)
class ApiKeyRecord:
    id: int
    name: str
    key_prefix: str
    scopes: list[str]
    active: bool


@dataclass(frozen=True)
class JobRecord:
    id: int
    public_id: str
    workload_id: int
    workload_slug: str
    status: str
    payload: dict[str, Any]
    pipeline_run_id: int | None
    rabbit_message_id: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    finished_at: str | None


class WorkloadRepository:
    def __init__(self, db: DatabaseConfig | str) -> None:
        self.db = resolve_database(db)

    def get_by_slug(self, slug: str) -> WorkloadRecord | None:
        with get_connection(self.db) as conn:
            row = conn.execute(
                """
                SELECT w.*, p.slug AS gpu_pool_slug
                FROM atlas.workloads w
                LEFT JOIN atlas.gpu_pools p ON p.id = w.gpu_pool_id
                WHERE w.slug = ?
                """,
                (slug.strip(),),
            ).fetchone()
        return self._row_to_workload(row) if row else None

    def _row_to_workload(self, row) -> WorkloadRecord:
        config = row["config_json"]
        if isinstance(config, str):
            config = json.loads(config)
        return WorkloadRecord(
            id=int(row["id"]),
            slug=str(row["slug"]),
            name=str(row["name"]),
            image=str(row["image"]),
            queue_name=str(row["queue_name"]),
            k8s_namespace=str(row["k8s_namespace"]),
            gpu_pool_slug=str(row["gpu_pool_slug"]) if row["gpu_pool_slug"] else None,
            active=bool(row["active"]),
            config_json=dict(config or {}),
        )


class ApiKeyRepository:
    def __init__(self, db: DatabaseConfig | str) -> None:
        self.db = resolve_database(db)

    def get_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        with get_connection(self.db) as conn:
            row = conn.execute(
                """
                SELECT id, name, key_prefix, scopes, active
                FROM atlas.api_keys
                WHERE key_hash = ? AND active = TRUE
                """,
                (key_hash,),
            ).fetchone()
        return self._row_to_key(row) if row else None

    def _row_to_key(self, row) -> ApiKeyRecord:
        scopes = row["scopes"]
        if isinstance(scopes, str):
            scopes = json.loads(scopes)
        return ApiKeyRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            key_prefix=str(row["key_prefix"]),
            scopes=[str(item) for item in (scopes or [])],
            active=bool(row["active"]),
        )


class JobRepository:
    def __init__(self, db: DatabaseConfig | str) -> None:
        self.db = resolve_database(db)

    def create_job(
        self,
        *,
        public_id: str,
        workload_id: int,
        payload: dict[str, Any],
        pipeline_run_id: int | None = None,
    ) -> JobRecord:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with get_connection(self.db) as conn:
            cursor = conn.execute(
                """
                INSERT INTO atlas.jobs (
                    public_id, workload_id, status, payload, pipeline_run_id
                ) VALUES (?, ?, 'queued', ?::jsonb, ?)
                """,
                (public_id, workload_id, payload_json, pipeline_run_id),
            )
            job_id = int(cursor.lastrowid or 0)
            row = conn.execute(
                """
                SELECT j.*, w.slug AS workload_slug
                FROM atlas.jobs j
                JOIN atlas.workloads w ON w.id = j.workload_id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        assert row is not None
        return self._row_to_job(row)

    def get_by_public_id(self, public_id: str) -> JobRecord | None:
        with get_connection(self.db) as conn:
            row = conn.execute(
                """
                SELECT j.*, w.slug AS workload_slug
                FROM atlas.jobs j
                JOIN atlas.workloads w ON w.id = j.workload_id
                WHERE j.public_id = ?
                """,
                (public_id.strip(),),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def set_rabbit_message_id(self, job_id: int, message_id: str) -> None:
        with get_connection(self.db) as conn:
            conn.execute(
                """
                UPDATE atlas.jobs
                SET rabbit_message_id = ?, updated_at = now()
                WHERE id = ?
                """,
                (message_id, job_id),
            )
            conn.commit()

    def update_status(
        self,
        job_id: int,
        *,
        status: str,
        error_message: str | None = None,
        finished: bool = False,
    ) -> None:
        with get_connection(self.db) as conn:
            if finished:
                conn.execute(
                    """
                    UPDATE atlas.jobs
                    SET status = ?,
                        error_message = ?,
                        finished_at = now(),
                        updated_at = now()
                    WHERE id = ?
                    """,
                    (status, error_message, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE atlas.jobs
                    SET status = ?,
                        error_message = ?,
                        updated_at = now()
                    WHERE id = ?
                    """,
                    (status, error_message, job_id),
                )
            conn.commit()

    def sync_status_from_pipeline_run(self, job: JobRecord) -> JobRecord:
        run_id = job.pipeline_run_id or job.payload.get("run_id")
        if run_id is None:
            return job
        with get_connection(self.db) as conn:
            row = conn.execute(
                """
                SELECT status, error_message, finished_at
                FROM pipeline_runs
                WHERE id = ?
                """,
                (int(run_id),),
            ).fetchone()
        if row is None:
            return job

        pipeline_status = str(row["status"])
        mapped = _map_pipeline_status(pipeline_status)
        if mapped == job.status and not row["finished_at"]:
            return job

        error_message = str(row["error_message"]) if row["error_message"] else None
        finished_at = row["finished_at"]
        finished = mapped in {"completed", "failed", "cancelled"}

        with get_connection(self.db) as conn:
            conn.execute(
                """
                UPDATE atlas.jobs
                SET status = ?,
                    error_message = COALESCE(?, error_message),
                    finished_at = CASE WHEN ? THEN COALESCE(finished_at, now()) ELSE finished_at END,
                    updated_at = now(),
                    pipeline_run_id = COALESCE(pipeline_run_id, ?)
                WHERE id = ?
                """,
                (
                    mapped,
                    error_message,
                    finished,
                    int(run_id),
                    job.id,
                ),
            )
            conn.commit()

        refreshed = self.get_by_public_id(job.public_id)
        assert refreshed is not None
        if finished_at and refreshed.finished_at is None:
            return refreshed
        return refreshed

    def _row_to_job(self, row) -> JobRecord:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return JobRecord(
            id=int(row["id"]),
            public_id=str(row["public_id"]),
            workload_id=int(row["workload_id"]),
            workload_slug=str(row["workload_slug"]),
            status=str(row["status"]),
            payload=dict(payload or {}),
            pipeline_run_id=int(row["pipeline_run_id"])
            if row["pipeline_run_id"] is not None
            else None,
            rabbit_message_id=str(row["rabbit_message_id"])
            if row["rabbit_message_id"]
            else None,
            error_message=str(row["error_message"]) if row["error_message"] else None,
            created_at=_iso(row["created_at"]),
            updated_at=_iso(row["updated_at"]),
            finished_at=_iso(row["finished_at"]) if row["finished_at"] else None,
        )


def _map_pipeline_status(status: str) -> str:
    mapping = {
        "queued": "queued",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return mapping.get(status, status)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)
