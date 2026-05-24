#!/usr/bin/env python3
"""Inicializa SQLite + usuário admin (servidor web)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVER_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core" / "src"))

from track_fraude_core.db import init_database
from server.settings import load_settings
from server.users import UserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Init DB para o painel web.")
    parser.add_argument(
        "--settings",
        default=str(SERVER_DIR / "config" / "settings.yaml"),
    )
    args = parser.parse_args()

    settings = load_settings(args.settings)
    db_path = init_database(settings.database_path)
    print(f"Schema OK: {db_path}")

    user_repo = UserRepository(settings.database_path)
    user_repo.seed_admin(
        username=settings.admin_username,
        password=settings.admin_password,
        display_name=settings.admin_display_name,
    )
    print(f"Usuário admin: {settings.admin_username}")
    print("Cadastre lojas em /stores após subir o servidor.")


if __name__ == "__main__":
    main()
