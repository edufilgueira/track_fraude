from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.services.video_storage import format_date_br, list_raw_import_dates
from track_fraude_core.db import GroupRepository, StoreRepository


@pytest.fixture(autouse=True)
def isolated_editor_frames(monkeypatch, tmp_path: Path):
    frames_root = tmp_path / "editor_frames"
    monkeypatch.setattr(
        "server.services.editor_frame_storage.EDITOR_FRAMES_ROOT", frames_root
    )
    monkeypatch.setattr(
        "server.services.editor_frame_storage.LEGACY_DATA_FRAMES_ROOT",
        tmp_path / "legacy_editor_frames",
    )


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def settings_path(db_path: Path, tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(
        f"""
app:
  secret_key: test-secret
database:
  path: {db_path.as_posix()}
auth:
  admin_username: admin
  admin_password: admin123
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def client(settings_path: Path, project_root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr("server.dependencies.PROJECT_ROOT", project_root)
    monkeypatch.setattr("server.services.video_storage.PROJECT_ROOT", project_root)
    return TestClient(create_app(settings_path))


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def test_list_raw_import_dates_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("server.services.video_storage.PROJECT_ROOT", tmp_path)
    assert list_raw_import_dates(group_code="default", store_id="LOJA-01") == []


def test_format_date_br():
    assert format_date_br("2026-05-23") == "23/05/2026"


def test_raw_dates_api(
    client: TestClient,
    project_root: Path,
    db_path: Path,
):
    group_repo = GroupRepository(db_path)
    group = group_repo.list_groups()[0]
    store_repo = StoreRepository(db_path)
    store = store_repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-01",
        name="Loja Teste",
    )
    raw_dir = project_root / "data" / "raw" / "default" / "LOJA-01" / "2026-05-22"
    raw_dir.mkdir(parents=True)
    (raw_dir / "cam1.mp4").write_bytes(b"x")

    login(client)
    response = client.get(f"/api/pipeline/stores/{store.id}/raw-dates")
    assert response.status_code == 200
    payload = response.json()
    assert payload["dates"] == [{"id": "2026-05-22", "label": "22/05/2026"}]


def test_pipeline_status_degraded_on_sqlite_error(client: TestClient, monkeypatch):
    class BrokenRepo:
        def list_running(self):
            raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(
        "server.routes.pipeline_api.get_pipeline_run_repo",
        lambda: BrokenRepo(),
    )
    monkeypatch.setattr(
        "server.routes.pipeline_api.list_running_store_ids_locally",
        lambda: [7],
    )

    login(client)
    response = client.get("/api/pipeline/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stores_processing"] == [7]
    assert payload.get("degraded") is True


def test_pipeline_log_api_survives_sqlite_error(
    client: TestClient,
    project_root: Path,
    db_path: Path,
    monkeypatch,
):
    group_repo = GroupRepository(db_path)
    group = group_repo.list_groups()[0]
    store_repo = StoreRepository(db_path)
    store = store_repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-SQLITE",
        name="Loja SQLite",
    )
    log_dir = project_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pipeline_{store.id}_2026-05-22_test.log"
    log_path.write_text("pipeline ok\n", encoding="utf-8")

    from server.services import pipeline_runner

    pipeline_runner._log_files[store.id] = log_path

    class BrokenStoreRepo:
        def get_store(self, store_db_id: int):
            raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(
        "server.routes.pipeline_api.get_store_repo",
        lambda: BrokenStoreRepo(),
    )

    login(client)
    response = client.get(f"/api/pipeline/stores/{store.id}/log?offset=0")
    assert response.status_code == 200
    assert "pipeline ok" in response.json()["content"]


def test_pipeline_log_api(
    client: TestClient,
    project_root: Path,
    db_path: Path,
):
    group_repo = GroupRepository(db_path)
    group = group_repo.list_groups()[0]
    store_repo = StoreRepository(db_path)
    store = store_repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-LOG",
        name="Loja Log",
    )
    log_dir = project_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pipeline_{store.id}_2026-05-22_test.log"
    log_path.write_text("linha 1\nlinha 2\n", encoding="utf-8")

    from server.services import pipeline_runner

    pipeline_runner._log_files[store.id] = log_path

    login(client)
    response = client.get(f"/api/pipeline/stores/{store.id}/log?offset=0")
    assert response.status_code == 200
    payload = response.json()
    assert "linha 1" in payload["content"]
    assert payload["offset"] > 0
    assert payload["has_log"] is True

    response2 = client.get(
        f"/api/pipeline/stores/{store.id}/log?offset={payload['offset']}"
    )
    assert response2.json()["content"] == ""


def test_review_available_api(
    client: TestClient,
    project_root: Path,
    db_path: Path,
):
    group_repo = GroupRepository(db_path)
    group = group_repo.list_groups()[0]
    store_repo = StoreRepository(db_path)
    store = store_repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-REV",
        name="Loja Rev",
    )
    review_dir = (
        project_root
        / "data"
        / "processed"
        / group.group_code
        / store.store_id
        / "2026-05-22"
        / "review"
    )
    review_dir.mkdir(parents=True)
    (review_dir / "index.json").write_text('{"alerts":[]}', encoding="utf-8")

    login(client)
    response = client.get(f"/api/pipeline/stores/{store.id}/review-available")
    assert response.status_code == 200
    assert response.json()["has_review"] is True

