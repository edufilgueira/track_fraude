#!/usr/bin/env python3
"""Migra dados do SQLite atual para um Postgres vazio."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable

TABLES = (
    "groups",
    "stores",
    "cameras",
    "users",
    "camera_zones",
    "pipeline_runs",
    "alert_reviews",
)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def _copy_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> int:
    columns = _columns(sqlite_conn, table)
    if not columns:
        return 0

    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    quoted_columns = ", ".join(columns)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "id")
    conflict = f"ON CONFLICT (id) DO UPDATE SET {updates}" if "id" in columns else ""
    sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) {conflict}"

    with pg_conn.cursor() as cursor:
        cursor.executemany(sql, [tuple(row[column] for column in columns) for row in rows])
    return len(rows)


def _reset_sequences(pg_conn, tables: Iterable[str]) -> None:
    with pg_conn.cursor() as cursor:
        for table in tables:
            cursor.execute(
                """
                SELECT pg_get_serial_sequence(%s, 'id')
                """,
                (table,),
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                continue
            cursor.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 1), true)",
                (row[0],),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Copia SQLite do track_fraude para Postgres.")
    parser.add_argument("--sqlite", default="data/track_fraude.db", help="Caminho do SQLite")
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Ex.: postgresql://track_fraude:senha@localhost:5432/track_fraude",
    )
    args = parser.parse_args()

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit('Instale antes: python -m pip install "psycopg[binary]>=3.1"') from exc

    sqlite_path = Path(args.sqlite)
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    with psycopg.connect(args.postgres_url) as pg_conn:
        with pg_conn.transaction():
            for table in TABLES:
                copied = _copy_table(sqlite_conn, pg_conn, table)
                print(f"{table}: {copied} linhas")
            _reset_sequences(pg_conn, TABLES)


if __name__ == "__main__":
    main()
