from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from track_fraude_core.db import GroupRepository, StoreRepository, init_database


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    init_database(path)
    return path


@pytest.fixture
def settings_path(db_path: Path, tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(
        f"""
app:
  secret_key: test-secret
  host: 127.0.0.1
  port: 8080
database:
  path: {db_path.as_posix()}
auth:
  admin_username: admin
  admin_password: admin123
  admin_display_name: Admin Teste
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def group_repo(db_path: Path) -> GroupRepository:
    return GroupRepository(db_path)


@pytest.fixture
def repo(db_path: Path) -> StoreRepository:
    return StoreRepository(db_path)


@pytest.fixture
def client(settings_path: Path) -> TestClient:
    app = create_app(settings_path)
    return TestClient(app)


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_store_with_camera(repo: StoreRepository, group_repo: GroupRepository) -> tuple[int, int]:
    group = group_repo.create_group(group_code="cometa", name="Cometa")
    store = repo.create_store(
        group_db_id=group.id,
        store_id="LOJA-01",
        name="Loja Teste",
    )
    camera = repo.create_camera(
        store_db_id=store.id,
        camera_id="cam2",
        description="Checkout",
        ocr_x=12,
        ocr_y=18,
        ocr_width=400,
        ocr_height=48,
    )
    return store.id, camera.id


def test_roi_save_api(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_store_with_camera(repo, group_repo)
    login(client)

    response = client.post(
        f"/stores/{store_id}/cameras/{camera_id}/roi",
        json={"ocr_x": 20, "ocr_y": 25, "ocr_width": 300, "ocr_height": 40},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["roi"]["ocr_x"] == 20

    updated = repo.get_camera(camera_id)
    assert updated is not None
    assert updated.ocr_width == 300


def test_roi_editor_page_has_file_picker(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_store_with_camera(repo, group_repo)
    login(client)

    response = client.get(f"/stores/{store_id}/cameras/{camera_id}/roi-editor")
    assert response.status_code == 200
    assert "Selecionar ROI" in response.text
    assert 'id="video-file"' in response.text
    assert "roi_editor.js" in response.text


def test_frame_upload_extracts_jpeg(
    client: TestClient,
    repo: StoreRepository,
    group_repo: GroupRepository,
    tmp_path: Path,
):
    pytest.importorskip("cv2")
    import cv2
    import numpy as np

    store_id, camera_id = seed_store_with_camera(repo, group_repo)
    login(client)

    video_path = tmp_path / "cam2_test.mp4"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        25,
        (640, 360),
    )
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:] = (30, 30, 30)
    cv2.putText(frame, "08:00:00", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    writer.write(frame)
    writer.release()

    with video_path.open("rb") as handle:
        response = client.post(
            f"/stores/{store_id}/cameras/{camera_id}/frame-upload",
            files={"video": ("cam2_test.mp4", handle, "video/mp4")},
            data={"seconds": "0"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert int(response.headers["X-Frame-Width"]) == 640
    assert len(response.content) > 1000
