from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from atlas.db.repositories import JobRecord
from atlas.platform.app import create_app
from atlas.platform.services.job_service import JobService, JobServiceError
from atlas.platform.settings import PlatformSettings, hash_api_key
from track_fraude_core.db.database import DatabaseConfig


@pytest.fixture
def platform_settings() -> PlatformSettings:
    return PlatformSettings(
        host="127.0.0.1",
        port=8090,
        database=DatabaseConfig.from_settings(
            backend="postgres",
            postgres_url="postgresql://test:test@127.0.0.1:5432/test",
        ),
        rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/%2F",
        require_api_key=False,
    )


@pytest.fixture
def client(platform_settings: PlatformSettings):
    with patch("atlas.platform.app.init_atlas_schema"):
        app = create_app(platform_settings)
        with TestClient(app) as test_client:
            yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["service"] == "atlas-platform-api"


def test_create_job_success(client: TestClient) -> None:
    job = JobRecord(
        id=1,
        public_id="job-abc",
        workload_id=1,
        workload_slug="track-fraude",
        status="queued",
        payload={"run_id": 7},
        pipeline_run_id=7,
        rabbit_message_id="pipeline-7",
        error_message=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        finished_at=None,
    )
    with patch.object(JobService, "create_job", return_value=job):
        response = client.post(
            "/v1/jobs",
            json={
                "workload": "track-fraude",
                "payload": {
                    "run_id": 7,
                    "store_db_id": 1,
                    "group_code": "default",
                    "store_id": "LOJA-01",
                    "date": "2026-05-22",
                    "db_path": "x",
                },
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "job-abc"
    assert body["workload"] == "track-fraude"


def test_create_job_service_error(client: TestClient) -> None:
    with patch.object(
        JobService,
        "create_job",
        side_effect=JobServiceError("payload incompleto", status_code=400),
    ):
        response = client.post(
            "/v1/jobs",
            json={"workload": "track-fraude", "payload": {}},
        )
    assert response.status_code == 400


def test_api_key_hash_matches_seed() -> None:
    assert hash_api_key("atlas-dev-internal-key") == (
        "f50f6d80fc9c1dcfa54cf266d21cca3f3051f784a260681b00673b7def088034"
    )


def test_job_service_scope_denied() -> None:
    service = JobService(
        database_dsn="postgresql://x",
        rabbitmq_url="amqp://x",
    )
    with pytest.raises(JobServiceError) as exc:
        service.create_job(
            workload_slug="track-fraude",
            payload={"run_id": 1},
            scopes=["other:enqueue"],
        )
    assert exc.value.status_code == 403
