#!/usr/bin/env python3
"""Cadastra grupo demo + loja LOJA-01 para dev/testes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))

from track_fraude_core.db import GroupRepository, StoreRepository, init_database


def seed_demo_store(
    db_path: Path,
    *,
    group_code: str = "cometa",
    group_name: str = "Grupo Cometa",
    store_id: str = "LOJA-01",
) -> None:
    init_database(db_path)
    group_repo = GroupRepository(db_path)
    store_repo = StoreRepository(db_path)

    group = group_repo.get_group_by_code(group_code)
    if group is None:
        group = group_repo.create_group(group_code=group_code, name=group_name)
        print(f"Grupo criado: {group_code}")

    existing = store_repo.get_store_by_code(store_id, group_db_id=group.id)
    if existing:
        print(f"Loja já existe: {store_id} (grupo {group_code})")
        return

    store = store_repo.create_store(
        group_db_id=group.id,
        store_id=store_id,
        name="Loja Piloto Centro",
        street="Av. Paulista",
        number="1000",
        neighborhood="Bela Vista",
        city="São Paulo",
        state="SP",
        cep="",
        timezone="America/Sao_Paulo",
        ocr_sample_interval_sec=30,
        ocr_min_confidence=0.5,
        pos_match_delta_sec=60,
    )
    for camera_id, description, role in (
        ("cam1", "Entrada", "entrance"),
        ("cam2", "Checkout", "checkout"),
    ):
        store_repo.create_camera(
            store_db_id=store.id,
            camera_id=camera_id,
            description=description,
            camera_role=role,
            ocr_x=10,
            ocr_y=10,
            ocr_width=420,
            ocr_height=50,
        )
    print(f"Loja demo criada: {store_id} no grupo {group_code} (cam1, cam2)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed grupo Cometa + LOJA-01 para dev.")
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "track_fraude.db"),
    )
    parser.add_argument("--group-code", default="cometa")
    parser.add_argument("--group-name", default="Grupo Cometa")
    parser.add_argument("--store-id", default="LOJA-01")
    args = parser.parse_args()
    seed_demo_store(
        Path(args.db),
        group_code=args.group_code,
        group_name=args.group_name,
        store_id=args.store_id,
    )


if __name__ == "__main__":
    main()
