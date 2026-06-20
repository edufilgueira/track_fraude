#!/usr/bin/env python3
"""Aplica schema Atlas em Postgres existente (Fase 1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atlas.db.schema import init_atlas_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplica infra/postgres/schema_atlas.sql")
    parser.add_argument(
        "--postgres-url",
        default="postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude",
    )
    args = parser.parse_args()
    init_atlas_schema(args.postgres_url)
    print("Schema atlas aplicado (ou já existia).")


if __name__ == "__main__":
    main()
