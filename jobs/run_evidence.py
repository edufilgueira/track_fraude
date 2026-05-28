#!/usr/bin/env python3
"""Job Fase 5: gera pacotes de evidência (clips + timeline) por alerta."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude.cli_store import add_store_cli_args, load_job_store_config
from track_fraude.evidence import build_evidence_pack, build_review_index
from track_fraude.evidence.store_config import evidence_window_from_store
from track_fraude.storage import (
    FilePipelineStateRepository,
    ProcessedScope,
    ReviewScope,
    processed_root,
    review_root,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera clips cam1/cam2 e pacote de revisão por alerta R1."
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_store_cli_args(parser, db_default=str(ROOT / "data" / "track_fraude.db"))
    parser.add_argument(
        "--buffer-before",
        type=float,
        default=None,
        help="Override: segundos antes do primeiro evento (default: loja no SQLite)",
    )
    parser.add_argument(
        "--buffer-after",
        type=float,
        default=None,
        help="Override: segundos depois do último evento (default: loja no SQLite)",
    )
    parser.add_argument(
        "--checkout-buffer-before",
        type=float,
        default=None,
        help="Override: segundos antes do checkout no clip cam2 (default: loja)",
    )
    parser.add_argument(
        "--checkout-buffer-after",
        type=float,
        default=None,
        help="Override: segundos depois do checkout no clip cam2 (default: loja)",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=300.0,
        help="Duração máxima do clip completo em segundos (default 300 = 5 min)",
    )
    parser.add_argument(
        "--skip-clips",
        action="store_true",
        help="Gera só JSON/summary (sem FFmpeg)",
    )
    args = parser.parse_args()

    config = load_job_store_config(args)
    processed = ProcessedScope.from_config(processed_root(ROOT), config)
    review = ReviewScope.from_config(review_root(ROOT), config)

    alerts_path = processed.alerts_index_path(args.date)
    if not alerts_path.is_file():
        raise FileNotFoundError(
            f"alerts/index.json não encontrado: {alerts_path}. "
            f"Execute run_alerts.py antes."
        )

    with alerts_path.open(encoding="utf-8") as handle:
        alerts_index = json.load(handle)

    alerts = alerts_index.get("alerts") or []
    if not alerts:
        print("Nenhum alerta para gerar evidência.")
        return

    window = evidence_window_from_store(config, max_duration_sec=args.max_duration)
    if args.buffer_before is not None or args.buffer_after is not None or (
        args.checkout_buffer_before is not None or args.checkout_buffer_after is not None
    ):
        from dataclasses import replace

        window = replace(
            window,
            buffer_before_sec=args.buffer_before
            if args.buffer_before is not None
            else window.buffer_before_sec,
            buffer_after_sec=args.buffer_after
            if args.buffer_after is not None
            else window.buffer_after_sec,
            checkout_buffer_before_sec=args.checkout_buffer_before
            if args.checkout_buffer_before is not None
            else window.checkout_buffer_before_sec,
            checkout_buffer_after_sec=args.checkout_buffer_after
            if args.checkout_buffer_after is not None
            else window.checkout_buffer_after_sec,
        )

    packs = []
    for alert in alerts:
        pack = build_evidence_pack(
            alert=alert,
            date=args.date,
            project_root=ROOT,
            processed=processed,
            review=review,
            config=config,
            window=window,
            skip_clips=args.skip_clips,
        )
        packs.append(pack)
        print(f"evidência: {pack.output_dir}")
        print(f"  arquivos: {', '.join(pack.files)}")

    review_index = build_review_index(alerts_index=alerts_index, packs=packs)
    review_index_path = review.review_index_path(args.date)
    review_index_path.parent.mkdir(parents=True, exist_ok=True)
    with review_index_path.open("w", encoding="utf-8") as handle:
        json.dump(review_index, handle, indent=2, ensure_ascii=False)

    state_repo = FilePipelineStateRepository(processed)
    state = state_repo.load(args.date)
    state["phases"]["evidence"]["status"] = "completed"
    state_repo.save(args.date, state)

    print(f"índice de revisão: {review_index_path}")
    print(f"pacotes gerados: {len(packs)}")


if __name__ == "__main__":
    main()
