from __future__ import annotations

from pathlib import Path

import pytest

from track_fraude.pipeline.daily import (
    PipelineRunConfig,
    PipelineStep,
    build_pipeline_steps,
    build_step_command,
    filter_pipeline_steps,
    run_pipeline_steps,
)


def _config(**overrides) -> PipelineRunConfig:
    base = {
        "project_root": Path("C:/proj"),
        "date": "2026-05-22",
        "store_id": "LOJA-01",
        "group_code": "default",
        "db_path": "C:/proj/data/track_fraude.db",
        "camera_ids": ["cam1", "cam2"],
    }
    base.update(overrides)
    return PipelineRunConfig(**base)


def test_build_pipeline_steps_includes_full_chain():
    steps = build_pipeline_steps(_config())
    phases = [step.phase for step in steps]
    assert phases[0] == "ingest"
    assert phases.count("sync") == 2
    assert phases.count("track") == 2
    assert phases.count("events") == 2
    assert "merge" in phases
    assert "pos_match" in phases
    assert "vision" in phases
    assert "alerts" in phases
    assert "evidence" in phases


def test_skip_vision_and_evidence():
    steps = build_pipeline_steps(_config(skip_vision=True, skip_evidence=True))
    phases = [step.phase for step in steps]
    assert "vision" not in phases
    assert "evidence" not in phases


def test_filter_from_merge():
    steps = filter_pipeline_steps(build_pipeline_steps(_config()), _config(from_phase="merge"))
    assert steps[0].phase == "merge"
    assert all(step.phase in {"merge", "pos_match", "vision", "alerts", "evidence"} for step in steps)


def test_filter_only_track_single_camera():
    steps = filter_pipeline_steps(
        build_pipeline_steps(_config()),
        _config(only_phase="track", only_camera="cam2"),
    )
    assert len(steps) == 1
    assert steps[0] == PipelineStep(
        "track",
        "cam2",
        "run_track.py",
        (
            "--date",
            "2026-05-22",
            "--store-id",
            "LOJA-01",
            "--db",
            "C:/proj/data/track_fraude.db",
            "--group-code",
            "default",
            "--camera",
            "cam2",
        ),
    )


def test_build_step_command_uses_jobs_dir():
    step = PipelineStep("merge", None, "run_merge.py", ("--date", "2026-05-22"))
    command = build_step_command(_config(), step)
    script = command[2]
    assert script.endswith("jobs\\run_merge.py") or script.endswith("jobs/run_merge.py")
    assert "--date" in command


def test_run_pipeline_steps_dry_run():
    calls: list[list[str]] = []

    def runner(command: list[str]) -> int:
        calls.append(command)
        return 0

    result = run_pipeline_steps(_config(dry_run=True), runner=runner)
    assert result.ok is True
    assert len(result.steps) > 0
    assert calls == []


def test_run_pipeline_steps_stops_on_failure():
    seen: list[str] = []

    def runner(command: list[str]) -> int:
        joined = " ".join(command)
        seen.append(joined)
        return 1 if "run_sync.py" in joined else 0

    result = run_pipeline_steps(_config(), runner=runner)
    assert result.ok is False
    assert len(seen) == 2


def test_only_camera_requires_per_camera_phase():
    with pytest.raises(ValueError, match="--camera só se aplica"):
        filter_pipeline_steps(
            build_pipeline_steps(_config()),
            _config(only_phase="merge", only_camera="cam1"),
        )
