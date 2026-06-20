from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from atlas.db.repositories import JobRecord
from atlas.platform.auth import AuthContext, authenticate_request
from atlas.platform.services.job_service import JobService, JobServiceError
from atlas.platform.settings import PlatformSettings


class CreateJobBody(BaseModel):
    workload: str = Field(..., min_length=1)
    payload: dict[str, Any]


def job_to_dict(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.public_id,
        "workload": job.workload_slug,
        "status": job.status,
        "payload": job.payload,
        "pipeline_run_id": job.pipeline_run_id,
        "rabbit_message_id": job.rabbit_message_id,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def build_jobs_router(settings: PlatformSettings) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["jobs"])
    service = JobService(
        database_dsn=settings.database_dsn,
        rabbitmq_url=settings.rabbitmq_url,
    )

    def _auth(request: Request) -> AuthContext:
        return authenticate_request(request, settings)

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "atlas-platform-api"}

    @router.post("/jobs")
    async def create_job(body: CreateJobBody, auth: AuthContext = Depends(_auth)) -> dict:
        try:
            job = service.create_job(
                workload_slug=body.workload,
                payload=body.payload,
                scopes=auth.scopes,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return job_to_dict(job)

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, auth: AuthContext = Depends(_auth)) -> dict:
        _ = auth
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job não encontrado")
        return job_to_dict(job)

    return router
