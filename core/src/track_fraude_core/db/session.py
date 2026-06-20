from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from track_fraude_core.db.database import DatabaseConfig, resolve_database
from track_fraude_core.db.dialect import adapt_sql_for_postgres, should_returning_id


class DbRow:
    def __init__(self, row: Any, columns: list[str]) -> None:
        self._mapping = {col: row[idx] for idx, col in enumerate(columns)}

    def __getitem__(self, key: str) -> Any:
        return self._mapping[key]

    def keys(self) -> set[str]:
        return set(self._mapping.keys())


class DbCursor:
    def __init__(self) -> None:
        self._rows: list[DbRow] = []
        self.lastrowid: int | None = None
        self.rowcount: int = 0

    def fetchone(self) -> DbRow | None:
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self) -> list[DbRow]:
        return list(self._rows)


class DbConnection:
    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._conn: Any = None

    def __enter__(self) -> DbConnection:
        if self._config.is_postgres:
            import psycopg

            self._conn = psycopg.connect(self._config.postgres_url or "")
        else:
            import sqlite3

            path = self._config.sqlite_path
            assert path is not None
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA busy_timeout = 30000")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._conn is None:
            return
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        self._conn = None

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> DbCursor:
        if self._conn is None:
            raise RuntimeError("Conexão não aberta")

        cursor = DbCursor()
        bound = tuple(params)

        if self._config.is_postgres:
            import psycopg

            pg_sql = adapt_sql_for_postgres(sql)
            if should_returning_id(pg_sql):
                pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
            with self._conn.cursor() as pg_cur:
                pg_cur.execute(pg_sql, bound)
                if pg_cur.description:
                    columns = [desc.name for desc in pg_cur.description]
                    cursor._rows = [DbRow(row, columns) for row in pg_cur.fetchall()]
                cursor.rowcount = pg_cur.rowcount
                if should_returning_id(adapt_sql_for_postgres(sql)) and cursor._rows:
                    cursor.lastrowid = int(cursor._rows[0]["id"])
            return cursor

        sqlite_cur = self._conn.execute(sql, bound)
        rows = sqlite_cur.fetchall()
        cursor._rows = list(rows)
        cursor.rowcount = sqlite_cur.rowcount
        cursor.lastrowid = sqlite_cur.lastrowid
        return cursor


def init_postgres_schema(postgres_url: str) -> None:
    import psycopg

    candidates = [
        Path(__file__).resolve().parents[4] / "infra" / "postgres" / "schema.sql",
        Path.cwd() / "infra" / "postgres" / "schema.sql",
    ]
    schema_path = next((item for item in candidates if item.is_file()), None)
    if schema_path is None:
        raise FileNotFoundError(
            "Schema Postgres não encontrado (infra/postgres/schema.sql)"
        )

    sql = schema_path.read_text(encoding="utf-8")
    with psycopg.connect(postgres_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'groups'"
            )
            if cur.fetchone() is None:
                cur.execute(sql)
        conn.commit()


def init_database(source: DatabaseConfig | Path | str | None = None) -> DatabaseConfig:
    config = resolve_database(source)
    if config.is_postgres:
        init_postgres_schema(config.postgres_url or "")
        return config

    from track_fraude_core.db.connection import _init_sqlite_database

    assert config.sqlite_path is not None
    _init_sqlite_database(config.sqlite_path)
    return config


def get_connection(source: DatabaseConfig | Path | str | None = None) -> DbConnection:
    return DbConnection(resolve_database(source))
