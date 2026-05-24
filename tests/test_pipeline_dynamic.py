from __future__ import annotations

from pathlib import Path

import pytest

from track_fraude.pipeline.state import sync_phase_status
from track_fraude.storage import (
    FilePipelineStateRepository,
    OutputScope,
    ProcessedScope,
)
from track_fraude_core.store_config import load_store_config


def test_processed_scope_from_config():
    scope = ProcessedScope.from_config(
        "data/processed",
        {"group_code": "cometa", "store_id": "LOJA-01"},
    )
    assert scope.date_dir("2026-05-22") == Path(
        "data/processed/cometa/LOJA-01/2026-05-22"
    )
    assert scope.sync_map_path("2026-05-22", "cam2") == Path(
        "data/processed/cometa/LOJA-01/2026-05-22/cam2/sync_map.json"
    )


def test_pipeline_state_uses_configured_cameras(tmp_path: Path):
    scope = ProcessedScope(
        root=tmp_path,
        group_code="cometa",
        store_id="LOJA-01",
    )
    repo = FilePipelineStateRepository(scope)
    state = repo.init_if_missing("2026-05-22", ["cam3"])

    assert list(state["cameras"].keys()) == ["cam3"]
    assert state["group_code"] == "cometa"
    assert state["store_id"] == "LOJA-01"
    assert state["phases"]["sync"]["status"] == "pending"


def test_pipeline_state_merges_new_camera(tmp_path: Path):
    scope = ProcessedScope(
        root=tmp_path,
        group_code="cometa",
        store_id="LOJA-01",
    )
    repo = FilePipelineStateRepository(scope)
    state = repo.init_if_missing("2026-05-22", ["cam1"])
    state["cameras"]["cam1"]["sync"] = "completed"
    repo.save("2026-05-22", state)

    merged = repo.init_if_missing("2026-05-22", ["cam1", "cam2"])
    assert merged["cameras"]["cam1"]["sync"] == "completed"
    assert merged["cameras"]["cam2"]["sync"] == "pending"


def test_sync_phase_status_only_counts_configured_cameras():
    state = {
        "cameras": {
            "cam1": {"sync": "completed"},
            "cam2": {"sync": "pending"},
            "legacy_cam": {"sync": "pending"},
        }
    }
    assert sync_phase_status(state, ["cam1"]) == "completed"
    assert sync_phase_status(state, ["cam1", "cam2"]) == "partial"
    assert sync_phase_status(state, ["cam1", "cam2", "cam3"]) == "partial"


def test_output_scope_from_config():
    scope = OutputScope.from_config(
        "data/output",
        {"group_code": "default", "store_id": "LOJA-01"},
    )
    assert scope.alerts_index_path("2026-05-22") == Path(
        "data/output/default/LOJA-01/2026-05-22/alerts/index.json"
    )
    assert scope.alert_dir("2026-05-22", "AL-0042") == Path(
        "data/output/default/LOJA-01/2026-05-22/alerts/AL-0042"
    )


def test_processed_scope_isolates_stores(tmp_path: Path):
    scope_a = ProcessedScope(root=tmp_path, group_code="cometa", store_id="LOJA-01")
    scope_b = ProcessedScope(root=tmp_path, group_code="cometa", store_id="LOJA-02")

    repo_a = FilePipelineStateRepository(scope_a)
    repo_b = FilePipelineStateRepository(scope_b)
    repo_a.init_if_missing("2026-05-22", ["cam1"])
    repo_b.init_if_missing("2026-05-22", ["cam2"])

    state_a = repo_a.load("2026-05-22")
    state_b = repo_b.load("2026-05-22")
    assert "cam1" in state_a["cameras"]
    assert "cam2" in state_b["cameras"]
    assert "cam2" not in state_a["cameras"]


def test_load_store_config_requires_group_when_duplicate_code(
    db_path: Path,
    repo: StoreRepository,
    group_repo: GroupRepository,
):
    g1 = group_repo.create_group(group_code="cometa", name="Cometa")
    g2 = group_repo.create_group(group_code="outro", name="Outro")
    repo.create_store(group_db_id=g1.id, store_id="LOJA-01", name="Loja A")
    repo.create_store(group_db_id=g2.id, store_id="LOJA-01", name="Loja B")

    with pytest.raises(ValueError, match="Múltiplas lojas"):
        load_store_config(store_id="LOJA-01", db_path=db_path)

    config = load_store_config(
        store_id="LOJA-01",
        group_code="cometa",
        db_path=db_path,
    )
    assert config["group_code"] == "cometa"
