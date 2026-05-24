from __future__ import annotations

from pathlib import Path

import pytest

from track_fraude_core.db import GroupRepository, StoreRepository, init_database


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    init_database(path)
    return path


@pytest.fixture
def group_repo(db_path: Path) -> GroupRepository:
    return GroupRepository(db_path)


@pytest.fixture
def repo(db_path: Path) -> StoreRepository:
    return StoreRepository(db_path)
