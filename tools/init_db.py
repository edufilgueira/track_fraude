#!/usr/bin/env python3
"""Inicializa schema SQLite (worker / processamento)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude_core.db import init_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cria/atualiza tabelas SQLite (lojas vêm do painel web)."
    )
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "track_fraude.db"),
        help="Caminho do SQLite (local ou rede)",
    )
    args = parser.parse_args()

    db_path = init_database(args.db)
    print(f"Schema OK: {db_path}")
    print("Cadastre lojas e câmeras pelo painel: python server/main.py")


if __name__ == "__main__":
    main()
