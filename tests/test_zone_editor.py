from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from track_fraude_core.db import GroupRepository, StoreRepository
from track_fraude_core.db.camera_roles import CAMERA_ROLE_CHECKOUT, CAMERA_ROLE_ENTRANCE
from track_fraude_core.store_config import load_store_config
from track_fraude.zones import load_zones_for_store_config


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
    path = tmp_path / "test.db"
    return path


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
def repo(db_path: Path) -> StoreRepository:
    return StoreRepository(db_path)


@pytest.fixture
def group_repo(db_path: Path) -> GroupRepository:
    return GroupRepository(db_path)


@pytest.fixture
def client(settings_path: Path) -> TestClient:
    return TestClient(create_app(settings_path))


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _ensure_group(group_repo: GroupRepository, code: str = "default") -> int:
    existing = group_repo.get_group_by_code(code)
    if existing:
        return existing.id
    return group_repo.create_group(group_code=code, name="Default").id


def seed_entrance_camera(repo: StoreRepository, group_repo: GroupRepository) -> tuple[int, int]:
    group_id = _ensure_group(group_repo)
    store = repo.create_store(group_db_id=group_id, store_id="LOJA-01", name="Loja")
    camera = repo.create_camera(
        store_db_id=store.id,
        camera_id="cam1",
        description="Porta",
        camera_role=CAMERA_ROLE_ENTRANCE,
    )
    return store.id, camera.id


def seed_checkout_camera(repo: StoreRepository, group_repo: GroupRepository) -> tuple[int, int]:
    group_id = _ensure_group(group_repo, "checkout-test")
    store = repo.create_store(group_db_id=group_id, store_id="LOJA-02", name="Loja 2")
    camera = repo.create_camera(
        store_db_id=store.id,
        camera_id="cam2",
        description="Caixa",
        camera_role=CAMERA_ROLE_CHECKOUT,
    )
    return store.id, camera.id


def test_save_portal_zone_in_sqlite(repo: StoreRepository, group_repo: GroupRepository):
    _store_id, camera_id = seed_entrance_camera(repo, group_repo)
    zone = repo.save_camera_zone(
        camera_db_id=camera_id,
        zone_type="portal",
        zone_id="portal",
        label="Porta",
        polygon=[[10, 10], [100, 10], [100, 100], [10, 100]],
        entry_vector=[0, 1],
    )
    assert zone.zone_id == "portal"
    assert zone.entry_vector == [0.0, 1.0]
    assert len(repo.list_camera_zones(camera_id)) == 1


def test_zones_in_store_config(repo: StoreRepository, group_repo: GroupRepository, db_path: Path):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    store = repo.get_store(store_id)
    assert store is not None
    repo.save_camera_zone(
        camera_db_id=camera_id,
        zone_type="checkout_lane",
        zone_id="checkout_lane_3",
        label="Caixa 3",
        lane_id=3,
        polygon=[[820, 300], [1120, 300], [1120, 650], [820, 650]],
    )
    config = load_store_config(
        store_id="LOJA-02",
        group_code="checkout-test",
        db_path=db_path,
    )
    zones = load_zones_for_store_config(config)
    assert zones is not None
    assert "cam2" in zones.cameras
    assert len(zones.cameras["cam2"].checkout_lanes) == 1
    assert zones.cameras["cam2"].checkout_lanes[0].lane_id == 3


def test_editor_frame_not_found(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    response = client.get(f"/stores/{store_id}/cameras/{camera_id}/editor-frame")
    assert response.status_code == 404


def test_editor_frame_saved_and_served(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository
):
    from server.services.editor_frame_storage import save_editor_frame

    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    save_editor_frame(
        store_db_id=store_id,
        camera_db_id=camera_id,
        camera_id="cam2",
        jpeg=b"\xff\xd8\xff\xd9",
        width=640,
        height=480,
        source="test",
    )
    login(client)
    response = client.get(f"/stores/{store_id}/cameras/{camera_id}/editor-frame")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers.get("x-editor-frame-url")


def test_editor_frame_legacy_migration(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository, tmp_path: Path
):
    from server.services import editor_frame_storage

    store_id, camera_db_id = seed_checkout_camera(repo, group_repo)
    legacy_dir = editor_frame_storage.EDITOR_FRAMES_ROOT / str(store_id) / str(camera_db_id)
    legacy_dir.mkdir(parents=True)
    legacy_jpeg = legacy_dir / "frame.jpg"
    legacy_jpeg.write_bytes(b"\xff\xd8\xff\xd9")

    login(client)
    response = client.get(f"/stores/{store_id}/cameras/{camera_db_id}/zone-editor")
    assert response.status_code == 200
    assert "Carregando frame salvo no servidor" in response.text

    migrated = editor_frame_storage.editor_frame_jpeg_path(
        store_db_id=store_id, camera_db_id=camera_db_id
    )
    assert migrated.exists()


def test_migrate_legacy_data_editor_frames(tmp_path: Path, monkeypatch):
    from server.services import editor_frame_storage

    frames_root = tmp_path / "upload" / "editor_frames"
    legacy_root = tmp_path / "data" / "editor_frames"
    monkeypatch.setattr(editor_frame_storage, "EDITOR_FRAMES_ROOT", frames_root)
    monkeypatch.setattr(editor_frame_storage, "LEGACY_DATA_FRAMES_ROOT", legacy_root)

    legacy_dir = legacy_root / "3" / "7"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "frame.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (legacy_dir / "frame.json").write_text(
        '{"store_db_id":3,"camera_db_id":7,"camera_id":"cam7"}',
        encoding="utf-8",
    )

    count = editor_frame_storage.migrate_legacy_data_editor_frames()
    assert count == 1
    target = frames_root / "3" / "7" / "frame.jpg"
    assert target.exists()
    meta = json.loads((frames_root / "3" / "7" / "frame.json").read_text(encoding="utf-8"))
    assert meta["camera_id"] == "cam7"


def test_zone_editor_page(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    response = client.get(f"/stores/{store_id}/cameras/{camera_id}/zone-editor")
    assert response.status_code == 200
    assert "Polígonos de zona" in response.text
    assert "zone_editor.js" in response.text
    assert 'id="lane-tabs"' in response.text
    assert 'id="add-lane"' in response.text
    assert 'id="r1-min-duration-sec"' not in response.text


def test_store_rules_page(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository
):
    store_id, _camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    response = client.get(f"/stores/{store_id}/rules")
    assert response.status_code == 200
    assert "Regras de alerta" in response.text
    assert 'name="r1_min_checkout_duration_sec"' in response.text
    assert 'name="pos_match_delta_sec"' in response.text
    assert 'name="t_return_sec"' in response.text
    assert 'name="buffer_before_sec"' in response.text
    assert 'name="vid_stride"' in response.text
    assert 'name="evidence_scale_width"' in response.text
    assert 'name="evidence_ffmpeg_preset"' in response.text
    assert 'name="evidence_crf"' in response.text
    assert 'name="checkout_buffer_after_sec"' in response.text


def test_save_store_rules_form(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository
):
    store_id, _camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    response = client.post(
        f"/stores/{store_id}/rules",
        data={
            "buffer_before_sec": "30",
            "buffer_after_sec": "25",
            "checkout_buffer_before_sec": "8",
            "checkout_buffer_after_sec": "7",
            "vid_stride": "8",
            "evidence_scale_width": "1280",
            "evidence_ffmpeg_preset": "faster",
            "evidence_crf": "30",
            "r1_min_checkout_duration_sec": "45",
            "pos_match_delta_sec": "25",
            "t_return_sec": "3600",
            "carry_confidence_threshold": "0.6",
            "r3_visual_margin": "3",
            "r4_min_items": "6",
            "r4_fast_duration_sec": "120",
            "r5_cancelled_delta_sec": "90",
            "enable_r4": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    store = repo.get_store(store_id)
    assert store is not None
    assert store.buffer_before_sec == 30
    assert store.buffer_after_sec == 25
    assert store.checkout_buffer_before_sec == 8
    assert store.checkout_buffer_after_sec == 7
    assert store.vid_stride == 8
    assert store.evidence_scale_width == 1280
    assert store.evidence_ffmpeg_preset == "faster"
    assert store.evidence_crf == 30
    assert store.r1_min_checkout_duration_sec == 45
    assert store.pos_match_delta_sec == 25
    assert store.t_return_sec == 3600
    assert store.carry_confidence_threshold == 0.6
    assert store.r3_visual_margin == 3
    assert store.r4_min_items == 6
    assert store.r4_fast_duration_sec == 120
    assert store.r5_cancelled_delta_sec == 90
    assert store.enable_r4 is True


def test_save_multiple_checkout_lanes_api(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository
):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    base = f"/stores/{store_id}/cameras/{camera_id}/zones"
    for lane_id, polygon in (
        (1, [[80, 300], [380, 300], [380, 650], [80, 650]]),
        (2, [[450, 300], [750, 300], [750, 650], [450, 650]]),
        (3, [[820, 300], [1120, 300], [1120, 650], [820, 650]]),
    ):
        response = client.post(
            base,
            json={
                "zone_type": "checkout_lane",
                "zone_id": f"checkout_lane_{lane_id}",
                "lane_id": lane_id,
                "label": f"Caixa {lane_id}",
                "polygon": polygon,
            },
        )
        assert response.status_code == 200

    zones = repo.list_camera_zones(camera_id)
    assert len(zones) == 3
    assert sorted(z.lane_id for z in zones) == [1, 2, 3]


def test_delete_checkout_lane_api(
    client: TestClient, repo: StoreRepository, group_repo: GroupRepository
):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    client.post(
        f"/stores/{store_id}/cameras/{camera_id}/zones",
        json={
            "zone_type": "checkout_lane",
            "zone_id": "checkout_lane_2",
            "lane_id": 2,
            "label": "Caixa 2",
            "polygon": [[100, 100], [200, 100], [200, 200], [100, 200]],
        },
    )
    response = client.delete(
        f"/stores/{store_id}/cameras/{camera_id}/zones/checkout_lane_2"
    )
    assert response.status_code == 200
    zones = repo.list_camera_zones(camera_id)
    assert zones == []


def test_zone_save_api(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_checkout_camera(repo, group_repo)
    login(client)
    response = client.post(
        f"/stores/{store_id}/cameras/{camera_id}/zones",
        json={
            "zone_type": "checkout_lane",
            "zone_id": "checkout_lane_2",
            "lane_id": 2,
            "label": "Caixa 2",
            "polygon": [[100, 100], [200, 100], [200, 200], [100, 200]],
        },
    )
    assert response.status_code == 200
    zones = repo.list_camera_zones(camera_id)
    assert len(zones) == 1
    assert zones[0].lane_id == 2


def test_camera_form_has_role_select(client: TestClient, repo: StoreRepository, group_repo: GroupRepository):
    store_id, camera_id = seed_entrance_camera(repo, group_repo)
    login(client)
    response = client.get(f"/stores/{store_id}/cameras/{camera_id}/edit")
    assert response.status_code == 200
    assert 'name="camera_role"' in response.text
    assert "Definir zona no vídeo" in response.text
