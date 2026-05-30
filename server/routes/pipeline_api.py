from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.dependencies import get_group_repo, get_project_root, get_pipeline_run_repo, get_store_repo
from server.services.review_loader import has_review_evidence
from server.services.pipeline_runner import (
    cancel_daily_pipeline,
    raw_dates_payload,
    read_pipeline_log,
    start_daily_pipeline,
)
from server.services.video_storage import raw_store_dir

router = APIRouter(prefix="/api/pipeline", tags=["pipeline-api"])


@router.get("/status")
async def pipeline_status() -> dict:
    repo = get_pipeline_run_repo()
    runs = repo.list_running()
    return {
        "running": [
            {
                "run_id": run.id,
                "store_db_id": run.store_db_id,
                "group_db_id": run.group_db_id,
                "group_code": run.group_code,
                "store_id": run.store_id,
                "date": run.date,
                "current_phase": run.current_phase,
                "current_camera": run.current_camera,
            }
            for run in runs
        ],
        "groups_processing": sorted(
            {run.group_db_id for run in runs if run.group_db_id is not None}
        ),
        "stores_processing": sorted({run.store_db_id for run in runs}),
    }


class RunPipelineBody(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.get("/stores/{store_db_id}/raw-dates")
async def store_raw_dates(store_db_id: int) -> dict:
    store_repo = get_store_repo()
    group_repo = get_group_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    group = group_repo.get_group(store.group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    dates = raw_dates_payload(group_code=group.group_code, store_id=store.store_id)
    raw_path = raw_store_dir(group_code=group.group_code, store_id=store.store_id)
    return {
        "dates": dates,
        "raw_path": raw_path.as_posix(),
    }


@router.post("/stores/{store_db_id}/run")
async def run_store_pipeline(store_db_id: int, body: RunPipelineBody) -> dict:
    store_repo = get_store_repo()
    group_repo = get_group_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    if not store.active:
        raise HTTPException(status_code=400, detail="Loja inativa")
    group = group_repo.get_group(store.group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")

    repo = get_pipeline_run_repo()
    if repo.is_store_running(store_db_id):
        raise HTTPException(status_code=409, detail="Pipeline já em execução para esta loja")

    try:
        run_id, log_path = start_daily_pipeline(
            project_root=get_project_root(),
            store_db_id=store_db_id,
            group_code=group.group_code,
            store_id=store.store_id,
            date=body.date,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    project_root = get_project_root()
    try:
        log_rel = log_path.relative_to(project_root).as_posix()
    except ValueError:
        log_rel = log_path.as_posix()

    return {"ok": True, "date": body.date, "run_id": run_id, "log_path": log_rel}


@router.get("/stores/{store_db_id}/log")
async def store_pipeline_log(
    store_db_id: int,
    offset: int = 0,
) -> dict:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    project_root = get_project_root()
    payload = read_pipeline_log(
        project_root=project_root,
        store_db_id=store_db_id,
        offset=max(0, offset),
    )
    run = get_pipeline_run_repo().get_running_for_store(store_db_id)
    if run is not None:
        payload["current_phase"] = run.current_phase
        payload["date"] = run.date
    return payload


@router.post("/stores/{store_db_id}/cancel")
async def cancel_store_pipeline(store_db_id: int) -> dict:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    cancelled = cancel_daily_pipeline(store_db_id=store_db_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Nenhuma execução em andamento")
    return {"ok": True, "cancelled": True}


@router.get("/stores/{store_db_id}/review-available")
async def store_review_available(store_db_id: int) -> dict:
    store_repo = get_store_repo()
    group_repo = get_group_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    group = group_repo.get_group(store.group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    project_root = get_project_root()
    return {
        "has_review": has_review_evidence(
            project_root, store, group_code=group.group_code
        ),
    }
