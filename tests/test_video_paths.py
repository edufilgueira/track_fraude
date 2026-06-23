from __future__ import annotations

from pathlib import Path

import pytest

from track_fraude.storage import RawScope, raw_root
from track_fraude.video_paths import resolve_video_path


@pytest.fixture(autouse=True)
def _clear_raw_root_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACK_FRAUDE_RAW_ROOT", raising=False)


def test_resolve_video_path_uses_group_store_date():
    root = Path("/project")
    path = resolve_video_path(
        root,
        date="2026-05-22",
        camera_id="cam1",
        store_id="LOJA-01",
        group_code="default",
    )
    assert path == Path(
        "/project/data/raw/default/LOJA-01/2026-05-22/cam1.mp4"
    )


def test_raw_scope_date_dir():
    scope = RawScope.from_config(
        raw_root("/project"),
        {"group_code": "default", "store_id": "LOJA-01"},
    )
    assert scope.date_dir("2026-05-22") == Path(
        "/project/data/raw/default/LOJA-01/2026-05-22"
    )
