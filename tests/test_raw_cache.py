from __future__ import annotations

import os
from pathlib import Path

import pytest

from track_fraude.storage import raw_root
from track_fraude.storage.raw_cache import (
    RAW_ROOT_OVERRIDE_ENV,
    stage_raw_videos_if_configured,
)
from track_fraude.video_paths import resolve_video_path


def test_raw_root_uses_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACK_FRAUDE_RAW_ROOT", "/cache/raw")
    assert raw_root("/app") == Path("/cache/raw")


def test_stage_raw_videos_copies_day_and_sets_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "app"
    cache_dir = tmp_path / "cache" / "raw"
    source_day = (
        project_root
        / "data"
        / "raw"
        / "default"
        / "LOJA-01"
        / "2026-05-22"
    )
    source_day.mkdir(parents=True)
    video = source_day / "cam1.mp4"
    video.write_bytes(b"fake-video")

    monkeypatch.setenv("TRACK_FRAUDE_RAW_CACHE_DIR", str(cache_dir))
    monkeypatch.delenv(RAW_ROOT_OVERRIDE_ENV, raising=False)

    dest_day = stage_raw_videos_if_configured(
        project_root=project_root,
        group_code="default",
        store_id="LOJA-01",
        date="2026-05-22",
    )

    assert dest_day == cache_dir / "default" / "LOJA-01" / "2026-05-22"
    assert (dest_day / "cam1.mp4").read_bytes() == b"fake-video"
    assert os.environ[RAW_ROOT_OVERRIDE_ENV] == str(cache_dir)

    path = resolve_video_path(
        project_root,
        date="2026-05-22",
        camera_id="cam1",
        store_id="LOJA-01",
        group_code="default",
    )
    assert path == dest_day / "cam1.mp4"

    monkeypatch.delenv(RAW_ROOT_OVERRIDE_ENV, raising=False)


def test_stage_raw_videos_skips_when_env_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TRACK_FRAUDE_RAW_CACHE_DIR", raising=False)
    result = stage_raw_videos_if_configured(
        project_root=tmp_path / "app",
        group_code="default",
        store_id="LOJA-01",
        date="2026-05-22",
    )
    assert result is None


def test_raw_root_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from track_fraude.storage.raw_cache import raw_root_override_env

    monkeypatch.delenv(RAW_ROOT_OVERRIDE_ENV, raising=False)
    assert raw_root_override_env() == {}

    monkeypatch.setenv(RAW_ROOT_OVERRIDE_ENV, "/cache/raw")
    assert raw_root_override_env() == {RAW_ROOT_OVERRIDE_ENV: "/cache/raw"}
