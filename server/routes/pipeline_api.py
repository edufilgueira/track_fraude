from __future__ import annotations

from fastapi import APIRouter

from server.dependencies import get_pipeline_run_repo

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
