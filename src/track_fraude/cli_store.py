from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from track_fraude_core.store_config import load_store_config


def add_store_cli_args(parser: argparse.ArgumentParser, *, db_default: str) -> None:
    parser.add_argument("--store-id", required=True, help="Código da loja (SQLite)")
    parser.add_argument(
        "--group-code",
        default=None,
        help="Código do grupo (obrigatório se houver lojas com mesmo store_id)",
    )
    parser.add_argument(
        "--db",
        default=db_default,
        help="Caminho do SQLite (mesmo do painel web)",
    )


def load_job_store_config(args: argparse.Namespace) -> dict[str, Any]:
    return load_store_config(
        store_id=args.store_id,
        group_code=args.group_code,
        db_path=args.db,
    )


def camera_ids_from_config(config: dict[str, Any]) -> list[str]:
    return sorted(config.get("cameras", {}).keys())


def validate_camera_in_config(config: dict[str, Any], camera_id: str) -> None:
    if camera_id not in config.get("cameras", {}):
        store_id = config.get("store_id", "?")
        raise ValueError(
            f"Câmera {camera_id!r} não cadastrada para {store_id!r}. "
            "Configure no painel web."
        )
