from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from track_fraude_core.db import GroupRepository, PipelineRunRepository, ReviewRepository, StoreRepository
from track_fraude_core.db.review_repository import REVIEW_STATUS_CONFIRMED


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
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


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
    return TestClient(create_app(settings_path))


@pytest.fixture
def group_repo(db_path: Path) -> GroupRepository:
    return GroupRepository(db_path)


@pytest.fixture
def store_repo(db_path: Path) -> StoreRepository:
    return StoreRepository(db_path)


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _seed_store(group_repo: GroupRepository, store_repo: StoreRepository):
    group = group_repo.list_groups()[0]
    store = store_repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-01",
        name="Loja Teste",
    )
    return group, store


def _write_review_pack(
    project_root: Path,
    *,
    group_code: str,
    store_id: str,
    date: str,
    alert_id: str = "AL-20260522-0001",
) -> None:
    alert_dir = (
        project_root
        / "data/processed"
        / group_code
        / store_id
        / date
        / "review"
        / alert_id
    )
    alert_dir.mkdir(parents=True, exist_ok=True)
    (alert_dir / "summary.txt").write_text("Resumo de teste", encoding="utf-8")
    (alert_dir / "cam1_clip.mp4").write_bytes(b"fake")
    index = {
        "date": date,
        "alerts": [
            {
                "alert_id": alert_id,
                "rule_id": "R1",
                "rule_ids": ["R1"],
                "severity": "high",
                "suspicion_score": 40.0,
                "summary": "Teste",
                "store_timeline": [
                    {"event": "left", "t": "2026-05-22T10:01:03", "zone_id": "portal"}
                ],
                "checkout_session": {"lane_id": 1},
                "pos_matches": [],
                "evidence_files": ["summary.txt", "cam1_clip.mp4"],
            }
        ],
    }
    index_path = alert_dir.parent / "index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")


def test_review_list_and_detail(
    client: TestClient,
    group_repo: GroupRepository,
    store_repo: StoreRepository,
    project_root: Path,
):
    login(client)
    group, store = _seed_store(group_repo, store_repo)
    _write_review_pack(
        project_root,
        group_code=group.group_code,
        store_id=store.store_id,
        date="2026-05-22",
    )

    group_page = client.get(f"/groups/{group.id}")
    assert group_page.status_code == 200
    assert "Revisão" in group_page.text

    list_page = client.get(f"/stores/{store.id}/review/2026-05-22")
    assert list_page.status_code == 200
    assert "AL-20260522-0001" in list_page.text

    detail = client.get(f"/stores/{store.id}/review/2026-05-22/AL-20260522-0001")
    assert detail.status_code == 200
    assert "cam1_clip.mp4" in detail.text
    assert "Resumo de teste" in detail.text


def test_review_decision(
    client: TestClient,
    group_repo: GroupRepository,
    store_repo: StoreRepository,
    project_root: Path,
    db_path: Path,
):
    login(client)
    group, store = _seed_store(group_repo, store_repo)
    _write_review_pack(
        project_root,
        group_code=group.group_code,
        store_id=store.store_id,
        date="2026-05-22",
    )

    response = client.post(
        f"/stores/{store.id}/review/2026-05-22/AL-20260522-0001",
        data={"status": "confirmed", "note": "Fraude confirmada"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    repo = ReviewRepository(db_path)
    decision = repo.get_decision(store.id, "2026-05-22", "AL-20260522-0001")
    assert decision is not None
    assert decision.status == REVIEW_STATUS_CONFIRMED
    assert decision.note == "Fraude confirmada"


def test_pipeline_status_api(
    client: TestClient,
    group_repo: GroupRepository,
    store_repo: StoreRepository,
    db_path: Path,
):
    login(client)
    _, store = _seed_store(group_repo, store_repo)
    pipeline_repo = PipelineRunRepository(db_path)
    run_id = pipeline_repo.start_run(store.id, "2026-05-22")
    pipeline_repo.update_run(run_id, current_phase="track", current_camera="cam1")

    response = client.get("/api/pipeline/status")
    assert response.status_code == 200
    payload = response.json()
    assert store.id in payload["stores_processing"]
    assert payload["running"][0]["current_phase"] == "track"

    pipeline_repo.finish_run(run_id, ok=True)
    response = client.get("/api/pipeline/status")
    assert response.json()["stores_processing"] == []
