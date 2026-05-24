from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from track_fraude_core.db import GroupRepository, StoreRepository
from track_fraude_core.store_config import load_store_config

ROOT = Path(__file__).resolve().parents[1]


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


def seed_group(group_repo: GroupRepository, code: str = "cometa") -> int:
    group = group_repo.create_group(group_code=code, name="Grupo Cometa")
    return group.id


def test_create_store_and_camera(repo: StoreRepository, group_repo: GroupRepository):
    group_id = seed_group(group_repo, "cometa")
    store = repo.create_store(
        group_db_id=group_id,
        store_id="LOJA-99",
        name="Test Store",
        street="Rua A",
        number="10",
        city="Recife",
        state="PE",
    )
    cam = repo.create_camera(
        store_db_id=store.id,
        camera_id="cam1",
        description="Entrada",
        ocr_x=5,
        ocr_y=8,
        ocr_width=400,
        ocr_height=48,
    )
    config = repo.to_config_dict(store)
    assert config["group_code"] == "cometa"
    assert config["store_id"] == "LOJA-99"
    assert config["address"]["city"] == "Recife"
    assert config["cameras"]["cam1"]["ocr_roi"]["x"] == 5
    assert cam.camera_id == "cam1"


def test_load_store_config_from_sqlite(db_path: Path, repo: StoreRepository, group_repo: GroupRepository):
    group_id = seed_group(group_repo)
    store = repo.create_store(group_db_id=group_id, store_id="LOJA-01", name="Loja Principal")
    repo.create_camera(store_db_id=store.id, camera_id="cam2", ocr_x=12, ocr_y=15)

    config = load_store_config(store_id="LOJA-01", db_path=db_path)
    assert config["cameras"]["cam2"]["ocr_roi"]["x"] == 12


def test_load_store_config_with_group_code(db_path: Path, repo: StoreRepository, group_repo: GroupRepository):
    g1 = group_repo.create_group(group_code="cometa", name="Cometa")
    g2 = group_repo.create_group(group_code="outro", name="Outro")
    repo.create_store(group_db_id=g1.id, store_id="LOJA-01", name="A")
    repo.create_store(group_db_id=g2.id, store_id="LOJA-01", name="B")

    config = load_store_config(store_id="LOJA-01", group_code="cometa", db_path=db_path)
    assert config["group_code"] == "cometa"


def test_load_store_config_requires_store_id_when_many(db_path: Path, repo: StoreRepository, group_repo: GroupRepository):
    g1 = seed_group(group_repo, "A")
    g2 = seed_group(group_repo, "B")
    repo.create_store(group_db_id=g1, store_id="LOJA-A", name="A")
    repo.create_store(group_db_id=g2, store_id="LOJA-B", name="B")
    with pytest.raises(ValueError, match="Múltiplas lojas"):
        load_store_config(db_path=db_path)


def test_login_page(client: TestClient):
    response = client.get("/login")
    assert response.status_code == 200
    assert "track_fraude" in response.text


def test_groups_require_login(client: TestClient):
    response = client.get("/groups", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_admin_create_group_and_store(client: TestClient, group_repo: GroupRepository, repo: StoreRepository):
    login(client)

    response = client.post(
        "/groups",
        data={"group_code": "cometa", "name": "Grupo Cometa", "active": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    group = group_repo.get_group_by_code("cometa")
    assert group is not None

    response = client.post(
        f"/groups/{group.id}/stores",
        data={
            "store_id": "LOJA-01",
            "name": "Loja Centro",
            "street": "Rua X",
            "number": "100",
            "neighborhood": "Centro",
            "city": "Fortaleza",
            "state": "CE",
            "cep": "12345678",
            "timezone": "America/Sao_Paulo",
            "ocr_sample_interval_sec": 30,
            "ocr_min_confidence": 0.5,
            "pos_match_delta_sec": 60,
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    store = repo.get_store_by_code("LOJA-01", group_db_id=group.id)
    assert store is not None
    assert store.city == "Fortaleza"
    assert store.cep == "12345678"


def test_admin_list_groups(client: TestClient, group_repo: GroupRepository):
    group_repo.create_group(group_code="cometa", name="Cometa")
    login(client)
    response = client.get("/groups")
    assert response.status_code == 200
    assert "cometa" in response.text
