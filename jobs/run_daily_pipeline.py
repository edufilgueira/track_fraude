#!/usr/bin/env python3
"""Job Fase 7: orquestra o pipeline diário ponta a ponta."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import (
    add_store_cli_args,
    camera_ids_from_config,
    load_job_store_config,
)
from track_fraude.pipeline.daily import (
    PIPELINE_PHASES,
    PipelineRunConfig,
    PipelineRunResult,
    PipelineStep,
    run_pipeline_steps,
)
from track_fraude.pos import DEFAULT_POS_API_URL
from track_fraude.storage import FilePipelineStateRepository, ProcessedScope, processed_root
from track_fraude_core.db.pipeline_run_repository import PipelineRunRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Executa INGEST → SYNC → TRACK → … → EVIDENCE para um dia/loja."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument(
        "--pos-root",
        default=str(ROOT / "data" / "pos"),
        help="Pasta raiz do JSON POS (modo arquivo)",
    )
    parser.add_argument(
        "--pos-api-url",
        default=None,
        help=f"URL da API POS (ex.: {DEFAULT_POS_API_URL})",
    )
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="Pula run_vision.py",
    )
    parser.add_argument(
        "--skip-evidence",
        action="store_true",
        help="Pula run_evidence.py",
    )
    parser.add_argument(
        "--from",
        dest="from_phase",
        choices=PIPELINE_PHASES,
        default=None,
        help="Inicia a partir desta fase (inclusive)",
    )
    parser.add_argument(
        "--only",
        dest="only_phase",
        choices=PIPELINE_PHASES,
        default=None,
        help="Executa somente esta fase",
    )
    parser.add_argument(
        "--camera",
        default=None,
        help="Com --only sync|track|events, limita à câmera informada",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista comandos sem executar",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="ID de execução já registrado no SQLite (painel web)",
    )
    args = parser.parse_args()

    run_id: int | None = (
        int(args.run_id) if not args.dry_run and args.run_id is not None else None
    )
    pipeline_repo = PipelineRunRepository(args.db)

    result: PipelineRunResult | None = None
    error_message: str | None = None

    def on_step_start(step: PipelineStep) -> None:
        if run_id is not None:
            pipeline_repo.update_run(
                run_id,
                current_phase=step.phase,
                current_camera=step.camera_id,
            )

    try:
        config_store = load_job_store_config(args)
        camera_ids = camera_ids_from_config(config_store)
        scope = ProcessedScope.from_config(processed_root(ROOT), config_store)

        run_config = PipelineRunConfig(
            project_root=ROOT,
            date=args.date,
            store_id=config_store["store_id"],
            group_code=config_store.get("group_code"),
            db_path=args.db,
            camera_ids=camera_ids,
            skip_vision=args.skip_vision,
            skip_evidence=args.skip_evidence,
            pos_root=args.pos_root,
            pos_api_url=args.pos_api_url,
            from_phase=args.from_phase,
            only_phase=args.only_phase,
            only_camera=args.camera,
            dry_run=args.dry_run,
        )

        print(
            f"pipeline diário: date={args.date} store={run_config.store_id} "
            f"group={run_config.group_code or 'default'} cameras={','.join(camera_ids)}"
        )

        if not args.dry_run and run_id is None:
            store_db_id = int(config_store.get("store_db_id") or 0)
            if store_db_id:
                run_id = pipeline_repo.start_run(store_db_id, args.date)

        if run_id is not None:
            pipeline_repo.mark_run_running(
                run_id,
                worker_node=os.getenv("NODE_NAME") or socket.gethostname(),
                worker_id=os.getenv("HOSTNAME"),
                job_id=os.getenv("JOB_NAME"),
            )
        result = run_pipeline_steps(run_config, on_step_start=on_step_start)
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        if run_id is not None:
            pipeline_repo.finish_run(
                run_id,
                ok=bool(result and result.ok),
                error_message=error_message,
            )

    assert result is not None

    summary = {
        "date": args.date,
        "store_id": run_config.store_id,
        "group_code": run_config.group_code,
        "ok": result.ok,
        "total_elapsed_sec": round(result.total_elapsed_sec, 2),
        "steps": [
            {
                "phase": item.step.phase,
                "camera_id": item.step.camera_id,
                "returncode": item.returncode,
                "elapsed_sec": round(item.elapsed_sec, 2),
            }
            for item in result.steps
        ],
    }

    if not args.dry_run:
        summary_path = scope.date_dir(args.date) / "pipeline_run_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
        print(f"\nresumo: {summary_path}")

        state_repo = FilePipelineStateRepository(scope)
        state = state_repo.init_if_missing(args.date, camera_ids)
        state["phases"]["daily_pipeline"] = {
            "status": "completed" if result.ok else "failed",
            "summary_path": str(summary_path.as_posix()),
            "total_elapsed_sec": summary["total_elapsed_sec"],
        }
        state_repo.save(args.date, state)

    print(f"tempo total: {result.total_elapsed_sec:.1f}s")
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
