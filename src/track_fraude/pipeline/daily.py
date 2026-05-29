from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PIPELINE_PHASES: tuple[str, ...] = (
    "ingest",
    "sync",
    "track",
    "events",
    "merge",
    "pos_match",
    "vision",
    "alerts",
    "evidence",
)

PerCameraPhase = frozenset({"sync", "track", "events"})


@dataclass(frozen=True)
class PipelineStep:
    phase: str
    camera_id: str | None
    job_script: str
    extra_args: tuple[str, ...] = ()


@dataclass
class PipelineRunConfig:
    project_root: Path
    date: str
    store_id: str
    group_code: str | None
    db_path: str
    camera_ids: list[str]
    skip_vision: bool = False
    skip_evidence: bool = False
    pos_root: str = "data/pos"
    pos_api_url: str | None = None
    from_phase: str | None = None
    only_phase: str | None = None
    only_camera: str | None = None
    dry_run: bool = False


@dataclass
class StepResult:
    step: PipelineStep
    returncode: int
    elapsed_sec: float
    command: list[str]


@dataclass
class PipelineRunResult:
    steps: list[StepResult] = field(default_factory=list)
    ok: bool = True

    @property
    def total_elapsed_sec(self) -> float:
        return sum(item.elapsed_sec for item in self.steps)


def _jobs_dir(project_root: Path) -> Path:
    return project_root / "jobs"


def _store_args(config: PipelineRunConfig) -> tuple[str, ...]:
    args = [
        "--date",
        config.date,
        "--store-id",
        config.store_id,
        "--db",
        config.db_path,
    ]
    if config.group_code:
        args.extend(["--group-code", config.group_code])
    return tuple(args)


def build_pipeline_steps(config: PipelineRunConfig) -> list[PipelineStep]:
    base = _store_args(config)
    steps: list[PipelineStep] = [
        PipelineStep("ingest", None, "run_ingest.py", base),
    ]

    for camera_id in sorted(config.camera_ids):
        cam_args = ("--camera", camera_id)
        steps.append(
            PipelineStep("sync", camera_id, "run_sync.py", base + cam_args)
        )
        steps.append(
            PipelineStep(
                "track",
                camera_id,
                "run_track.py",
                base + cam_args,
            )
        )
        steps.append(
            PipelineStep("events", camera_id, "run_events.py", base + cam_args)
        )

    steps.extend(
        [
            PipelineStep("merge", None, "run_merge.py", base),
            PipelineStep(
                "pos_match",
                None,
                "run_pos_match.py",
                base
                + (
                    ("--pos-api-url", config.pos_api_url)
                    if config.pos_api_url
                    else ("--pos-root", config.pos_root)
                ),
            ),
        ]
    )

    if not config.skip_vision:
        steps.append(PipelineStep("vision", None, "run_vision.py", base))

    steps.append(PipelineStep("alerts", None, "run_alerts.py", base))

    if not config.skip_evidence:
        steps.append(PipelineStep("evidence", None, "run_evidence.py", base))

    return steps


def _phase_index(phase: str) -> int:
    try:
        return PIPELINE_PHASES.index(phase)
    except ValueError as exc:
        raise ValueError(
            f"Fase desconhecida: {phase!r}. Opções: {', '.join(PIPELINE_PHASES)}"
        ) from exc


def filter_pipeline_steps(
    steps: list[PipelineStep], config: PipelineRunConfig
) -> list[PipelineStep]:
    filtered = list(steps)

    if config.only_phase:
        only = config.only_phase
        filtered = [step for step in filtered if step.phase == only]
        if config.only_camera:
            if only not in PerCameraPhase:
                raise ValueError(
                    f"--camera só se aplica a fases {sorted(PerCameraPhase)}"
                )
            filtered = [
                step for step in filtered if step.camera_id == config.only_camera
            ]

    if config.from_phase:
        start = _phase_index(config.from_phase)
        allowed = set(PIPELINE_PHASES[start:])
        filtered = [step for step in filtered if step.phase in allowed]

    return filtered


def build_step_command(config: PipelineRunConfig, step: PipelineStep) -> list[str]:
    script = _jobs_dir(config.project_root) / step.job_script
    return [sys.executable, str(script), *step.extra_args]


def run_pipeline_steps(
    config: PipelineRunConfig,
    *,
    runner: Callable[[list[str]], int] | None = None,
) -> PipelineRunResult:
    steps = filter_pipeline_steps(build_pipeline_steps(config), config)
    if not steps:
        raise ValueError("Nenhuma etapa selecionada para executar")

    run = runner or (lambda command: subprocess.run(command, check=False).returncode)
    result = PipelineRunResult()

    for step in steps:
        command = build_step_command(config, step)
        label = step.phase if step.camera_id is None else f"{step.phase}:{step.camera_id}"
        print(f"\n=== pipeline: {label} ===")
        print(" ".join(command))

        if config.dry_run:
            result.steps.append(StepResult(step=step, returncode=0, elapsed_sec=0.0, command=command))
            continue

        started = time.perf_counter()
        returncode = run(command)
        elapsed = time.perf_counter() - started
        result.steps.append(
            StepResult(
                step=step,
                returncode=returncode,
                elapsed_sec=elapsed,
                command=command,
            )
        )
        print(f"concluído em {elapsed:.1f}s (exit {returncode})")

        if returncode != 0:
            result.ok = False
            break

    return result
