from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/track_fraude.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_db_id INTEGER NOT NULL,
    store_id TEXT NOT NULL,
    name TEXT NOT NULL,
    street TEXT NOT NULL DEFAULT '',
    number TEXT NOT NULL DEFAULT '',
    neighborhood TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    cep TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    ocr_sample_interval_sec INTEGER NOT NULL DEFAULT 30,
    ocr_min_confidence REAL NOT NULL DEFAULT 0.5,
    pos_match_delta_sec INTEGER NOT NULL DEFAULT 60,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (group_db_id) REFERENCES groups(id) ON DELETE RESTRICT,
    UNIQUE (group_db_id, store_id)
);

CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_db_id INTEGER NOT NULL,
    camera_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    ocr_x INTEGER NOT NULL DEFAULT 10,
    ocr_y INTEGER NOT NULL DEFAULT 10,
    ocr_width INTEGER NOT NULL DEFAULT 420,
    ocr_height INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (store_db_id) REFERENCES stores(id) ON DELETE CASCADE,
    UNIQUE (store_db_id, camera_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_GROUP_CODE = "default"
DEFAULT_GROUP_NAME = "Grupo Padrão"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _ensure_default_group(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM groups WHERE group_code = ?",
        (DEFAULT_GROUP_CODE,),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = conn.execute(
        "INSERT INTO groups (group_code, name, active) VALUES (?, ?, 1)",
        (DEFAULT_GROUP_CODE, DEFAULT_GROUP_NAME),
    )
    return int(cursor.lastrowid)


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "stores"):
        return

    store_columns = _column_names(conn, "stores")

    if not _table_exists(conn, "groups"):
        conn.executescript(
            """
            CREATE TABLE groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

    default_group_id = _ensure_default_group(conn)

    additions = {
        "group_db_id": f"ALTER TABLE stores ADD COLUMN group_db_id INTEGER REFERENCES groups(id)",
        "street": "ALTER TABLE stores ADD COLUMN street TEXT NOT NULL DEFAULT ''",
        "number": "ALTER TABLE stores ADD COLUMN number TEXT NOT NULL DEFAULT ''",
        "neighborhood": "ALTER TABLE stores ADD COLUMN neighborhood TEXT NOT NULL DEFAULT ''",
        "city": "ALTER TABLE stores ADD COLUMN city TEXT NOT NULL DEFAULT ''",
        "state": "ALTER TABLE stores ADD COLUMN state TEXT NOT NULL DEFAULT ''",
    }
    for column, sql in additions.items():
        if column not in store_columns:
            conn.execute(sql)

    store_columns = _column_names(conn, "stores")
    if "cep" not in store_columns:
        if "cpf" in store_columns:
            conn.execute("ALTER TABLE stores RENAME COLUMN cpf TO cep")
        else:
            conn.execute("ALTER TABLE stores ADD COLUMN cep TEXT NOT NULL DEFAULT ''")

    conn.execute(
        "UPDATE stores SET group_db_id = ? WHERE group_db_id IS NULL",
        (default_group_id,),
    )


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "stores"):
        store_columns = _column_names(conn, "stores")
        if "group_db_id" in store_columns:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stores_group ON stores(group_db_id)"
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_group_store_id
                ON stores(group_db_id, store_id)
                """
            )
    if _table_exists(conn, "cameras"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cameras_store ON cameras(store_db_id)"
        )


def init_database(db_path: Path | str | None = None) -> Path:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    with get_connection(path) as conn:
        conn.executescript(SCHEMA)
        _migrate_legacy_schema(conn)
        _ensure_indexes(conn)
        conn.commit()
    return path
