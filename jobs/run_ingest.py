#!/usr/bin/env python3
"""Job Fase 7: valida vídeo/POS do dia antes do pipeline."""

from __future__ import annotations

import argparse
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
from track_fraude.ingest import save_ingest_report, validate_day_ingest
from track_fraude.pos import DEFAULT_POS_API_URL
from track_fraude.storage import FilePipelineStateRepository, ProcessedScope, processed_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida vídeos do dia, manifest opcional e POS."
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
        "--allow-missing-pos",
        action="store_true",
        help="Não falha se POS do dia estiver ausente (somente warning)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    camera_ids = camera_ids_from_config(config)
    scope = ProcessedScope.from_config(processed_root(ROOT), config)

    report = validate_day_ingest(
        project_root=ROOT,
        date=args.date,
        store_id=config["store_id"],
        group_code=str(config.get("group_code") or "default"),
        camera_ids=camera_ids,
        pos_root=args.pos_root,
        pos_api_url=args.pos_api_url,
    )

    report_path = scope.date_dir(args.date) / "ingest_report.json"
    save_ingest_report(report_path, report)

    state_repo = FilePipelineStateRepository(scope)
    state = state_repo.init_if_missing(args.date, camera_ids)
    state.setdefault("phases", {})["ingest"] = {
        "status": "completed" if report.ok else "failed",
        "report_path": str(report_path.as_posix()),
    }
    state_repo.save(args.date, state)

    print(f"ingest report: {report_path}")
    for issue in report.issues:
        print(f"  [{issue.level}] {issue.code}: {issue.message}")

    if not report.ok:
        raise SystemExit(1)

    if report.issues and not args.allow_missing_pos:
        pos_errors = [item for item in report.issues if item.code == "pos_invalid"]
        if pos_errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
