from __future__ import annotations

import sqlite3

from server.dependencies import get_pipeline_run_repo
from server.services.pipeline_runner import list_running_store_ids_locally
from track_fraude_core.db.pipeline_run_repository import PipelineRunRecord


def processing_maps() -> tuple[
    set[int], set[int], dict[int, PipelineRunRecord], dict[int, PipelineRunRecord]
]:
    try:
        runs = get_pipeline_run_repo().list_running()
    except sqlite3.OperationalError:
        store_ids = set(list_running_store_ids_locally())
        return set(), store_ids, {}, {}

    group_ids = {run.group_db_id for run in runs if run.group_db_id is not None}
    store_ids = {run.store_db_id for run in runs}
    by_store = {run.store_db_id: run for run in runs}
    by_group: dict[int, PipelineRunRecord] = {}
    for run in runs:
        if run.group_db_id is not None:
            by_group[int(run.group_db_id)] = run
    return group_ids, store_ids, by_store, by_group
