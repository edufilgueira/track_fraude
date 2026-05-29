from __future__ import annotations

from server.dependencies import get_pipeline_run_repo
from track_fraude_core.db.pipeline_run_repository import PipelineRunRecord


def processing_maps() -> tuple[
    set[int], set[int], dict[int, PipelineRunRecord], dict[int, PipelineRunRecord]
]:
    runs = get_pipeline_run_repo().list_running()
    group_ids = {run.group_db_id for run in runs if run.group_db_id is not None}
    store_ids = {run.store_db_id for run in runs}
    by_store = {run.store_db_id: run for run in runs}
    by_group: dict[int, PipelineRunRecord] = {}
    for run in runs:
        if run.group_db_id is not None:
            by_group[int(run.group_db_id)] = run
    return group_ids, store_ids, by_store, by_group
