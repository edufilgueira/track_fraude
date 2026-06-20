from __future__ import annotations

import uuid
from typing import Any

from atlas.db.repositories import JobRecord, JobRepository, WorkloadRepository
from atlas.platform.services.queue_publisher import QueuePublisher
from track_fraude_core.db.pipeline_run_repository import PipelineRunRepository
from track_fraude_core.pipeline_queue import PipelineQueueMessage


class JobServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class JobService:
    def __init__(
        self,
        *,
        database_dsn: str,
        rabbitmq_url: str,
    ) -> None:
        self._database_dsn = database_dsn
        self._publisher = QueuePublisher(queue_url=rabbitmq_url)
        self._workloads = WorkloadRepository(database_dsn)
        self._jobs = JobRepository(database_dsn)
        self._pipeline_runs: PipelineRunRepository | None = None

    @property
    def pipeline_runs(self) -> PipelineRunRepository:
        if self._pipeline_runs is None:
            self._pipeline_runs = PipelineRunRepository(self._database_dsn)
        return self._pipeline_runs

    def create_job(
        self,
        *,
        workload_slug: str,
        payload: dict[str, Any],
        scopes: list[str],
    ) -> JobRecord:
        slug = workload_slug.strip()
        self._require_scope(scopes, f"{slug}:enqueue")

        workload = self._workloads.get_by_slug(slug)
        if workload is None or not workload.active:
            raise JobServiceError(f"Workload não encontrado: {slug!r}", status_code=404)

        normalized = dict(payload)
        pipeline_run_id = self._coerce_int(normalized.get("run_id"))
        if pipeline_run_id is None:
            raise JobServiceError("payload.run_id é obrigatório para track-fraude")

        message = self._build_queue_message(normalized)
        public_id = str(uuid.uuid4())

        job = self._jobs.create_job(
            public_id=public_id,
            workload_id=workload.id,
            payload=normalized,
            pipeline_run_id=pipeline_run_id,
        )

        try:
            result = self._publisher.publish(
                queue_name=workload.queue_name,
                message=message,
            )
        except Exception as exc:
            self._jobs.update_status(
                job.id,
                status="failed",
                error_message=str(exc),
                finished=True,
            )
            self.pipeline_runs.cancel_run(pipeline_run_id)
            raise JobServiceError(
                f"Falha ao publicar na fila: {exc}", status_code=502
            ) from exc

        self._jobs.set_rabbit_message_id(job.id, result.message_id)
        self.pipeline_runs.set_job_id(pipeline_run_id, public_id)

        refreshed = self._jobs.get_by_public_id(public_id)
        assert refreshed is not None
        return refreshed

    def get_job(self, public_id: str) -> JobRecord | None:
        job = self._jobs.get_by_public_id(public_id)
        if job is None:
            return None
        return self._jobs.sync_status_from_pipeline_run(job)

    def _build_queue_message(self, payload: dict[str, Any]) -> PipelineQueueMessage:
        required = (
            "run_id",
            "store_db_id",
            "group_code",
            "store_id",
            "date",
            "db_path",
        )
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise JobServiceError(
                f"payload incompleto; faltam: {', '.join(missing)}"
            )

        return PipelineQueueMessage(
            run_id=int(payload["run_id"]),
            store_db_id=int(payload["store_db_id"]),
            group_code=str(payload["group_code"]),
            store_id=str(payload["store_id"]),
            date=str(payload["date"]),
            db_path=str(payload["db_path"]),
            pos_root=str(payload.get("pos_root") or "data/pos"),
            pos_api_url=payload.get("pos_api_url"),
            skip_vision=bool(payload.get("skip_vision", False)),
            skip_evidence=bool(payload.get("skip_evidence", False)),
            from_phase=payload.get("from_phase"),
            only_phase=payload.get("only_phase"),
            only_camera=payload.get("only_camera"),
            log_path=payload.get("log_path"),
        )

    @staticmethod
    def _require_scope(scopes: list[str], required: str) -> None:
        if "*" in scopes or required in scopes:
            return
        raise JobServiceError("API key sem permissão para este workload", status_code=403)

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
