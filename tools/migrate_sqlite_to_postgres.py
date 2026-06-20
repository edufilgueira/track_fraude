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


def _pg_columns(pg_conn, table: str) -> list[str]:
    with pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _pg_boolean_columns(pg_conn, table: str) -> set[str]:
    with pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND data_type = 'boolean'
            """,
            (table,),
        )
        return {str(row[0]) for row in cursor.fetchall()}


def _convert_value(column: str, value, boolean_columns: set[str]):
    if column in boolean_columns and value is not None:
        return bool(int(value))
    return value


def _row_to_tuple(row: sqlite3.Row, columns: list[str], boolean_columns: set[str]) -> tuple:
    return tuple(_convert_value(col, row[col], boolean_columns) for col in columns)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def _copy_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> int:
    sqlite_columns = _columns(sqlite_conn, table)
    if not sqlite_columns:
        return 0

    pg_column_set = set(_pg_columns(pg_conn, table))
    columns = [column for column in sqlite_columns if column in pg_column_set]
    skipped = [column for column in sqlite_columns if column not in pg_column_set]
    if skipped:
        print(f"  skip {table}: colunas só no SQLite → {', '.join(skipped)}")
    if not columns:
        return 0

    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if not rows:
        return 0

    boolean_columns = _pg_boolean_columns(pg_conn, table)
    placeholders = ", ".join(["%s"] * len(columns))
    quoted_columns = ", ".join(columns)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "id")
    conflict = f"ON CONFLICT (id) DO UPDATE SET {updates}" if "id" in columns else ""
    sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) {conflict}"

    payload = [_row_to_tuple(row, columns, boolean_columns) for row in rows]
    with pg_conn.cursor() as cursor:
        cursor.executemany(sql, payload)
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
