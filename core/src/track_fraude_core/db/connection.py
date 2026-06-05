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
    pos_match_delta_sec INTEGER NOT NULL DEFAULT 20,
    r1_min_checkout_duration_sec REAL NOT NULL DEFAULT 20,
    t_return_sec REAL NOT NULL DEFAULT 1800,
    r3_visual_margin INTEGER NOT NULL DEFAULT 2,
    carry_confidence_threshold REAL NOT NULL DEFAULT 0.55,
    r4_min_items INTEGER NOT NULL DEFAULT 5,
    r4_fast_duration_sec REAL NOT NULL DEFAULT 90,
    enable_r4 INTEGER NOT NULL DEFAULT 1,
    r5_cancelled_delta_sec INTEGER NOT NULL DEFAULT 60,
    buffer_before_sec REAL NOT NULL DEFAULT 20,
    buffer_after_sec REAL NOT NULL DEFAULT 20,
    checkout_buffer_before_sec REAL NOT NULL DEFAULT 5,
    checkout_buffer_after_sec REAL NOT NULL DEFAULT 5,
    vid_stride INTEGER NOT NULL DEFAULT 5,
    evidence_scale_width INTEGER,
    evidence_ffmpeg_preset TEXT NOT NULL DEFAULT 'fast',
    evidence_crf INTEGER NOT NULL DEFAULT 28,
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

CREATE TABLE IF NOT EXISTS camera_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_db_id INTEGER NOT NULL,
    zone_type TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    lane_id INTEGER,
    polygon_json TEXT NOT NULL,
    entry_vector_json TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (camera_db_id) REFERENCES cameras(id) ON DELETE CASCADE,
    UNIQUE (camera_db_id, zone_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_db_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    current_phase TEXT NOT NULL DEFAULT '',
    current_camera TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    FOREIGN KEY (store_db_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alert_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_db_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    reviewer_user_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (store_db_id) REFERENCES stores(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_user_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (store_db_id, date, alert_id)
);
"""

DEFAULT_GROUP_CODE = "default"
DEFAULT_GROUP_NAME = "Grupo Padrão"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.is_absolute():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(path), timeout=30.0)
    except sqlite3.OperationalError as exc:
        raise sqlite3.OperationalError(
            f"Não foi possível abrir o SQLite em {path}: {exc}"
        ) from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
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

    store_columns = _column_names(conn, "stores")
    if "r1_min_checkout_duration_sec" not in store_columns:
        conn.execute(
            "ALTER TABLE stores ADD COLUMN r1_min_checkout_duration_sec "
            "REAL NOT NULL DEFAULT 20"
        )

    store_columns = _column_names(conn, "stores")
    rule_column_migrations: list[tuple[str, str]] = [
        ("t_return_sec", "REAL NOT NULL DEFAULT 1800"),
        ("r3_visual_margin", "INTEGER NOT NULL DEFAULT 2"),
        ("carry_confidence_threshold", "REAL NOT NULL DEFAULT 0.55"),
        ("r4_min_items", "INTEGER NOT NULL DEFAULT 5"),
        ("r4_fast_duration_sec", "REAL NOT NULL DEFAULT 90"),
        ("enable_r4", "INTEGER NOT NULL DEFAULT 1"),
        ("r5_cancelled_delta_sec", "INTEGER NOT NULL DEFAULT 60"),
        ("buffer_before_sec", "REAL NOT NULL DEFAULT 20"),
        ("buffer_after_sec", "REAL NOT NULL DEFAULT 20"),
        ("checkout_buffer_before_sec", "REAL NOT NULL DEFAULT 5"),
        ("checkout_buffer_after_sec", "REAL NOT NULL DEFAULT 5"),
        ("vid_stride", "INTEGER NOT NULL DEFAULT 5"),
    ]
    for column, ddl in rule_column_migrations:
        if column not in store_columns:
            conn.execute(f"ALTER TABLE stores ADD COLUMN {column} {ddl}")
            store_columns.add(column)

    _migrate_evidence_ffmpeg_settings(conn)


def _migrate_evidence_ffmpeg_settings(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "stores"):
        return

    store_columns = _column_names(conn, "stores")
    additions = {
        "evidence_scale_width": "INTEGER",
        "evidence_ffmpeg_preset": "TEXT NOT NULL DEFAULT 'fast'",
        "evidence_crf": "INTEGER NOT NULL DEFAULT 28",
    }
    for column, ddl in additions.items():
        if column not in store_columns:
            conn.execute(f"ALTER TABLE stores ADD COLUMN {column} {ddl}")
            store_columns.add(column)

    if "evidence_clip_quality" not in store_columns:
        return

    mapping = {
        "normal": (None, "fast", 23),
        "compact": (1280, "faster", 28),
        "economy": (960, "veryfast", 32),
    }
    rows = conn.execute(
        "SELECT id, evidence_clip_quality FROM stores WHERE evidence_clip_quality IS NOT NULL"
    ).fetchall()
    for row in rows:
        quality = str(row["evidence_clip_quality"] or "normal").strip().lower()
        scale, preset, crf = mapping.get(quality, (None, "fast", 28))
        conn.execute(
            """
            UPDATE stores
            SET evidence_scale_width = ?,
                evidence_ffmpeg_preset = ?,
                evidence_crf = ?
            WHERE id = ?
              AND evidence_scale_width IS NULL
              AND evidence_ffmpeg_preset = 'fast'
              AND evidence_crf = 28
            """,
            (scale, preset, crf, int(row["id"])),
        )


def _migrate_cameras_and_zones(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "cameras"):
        return

    camera_columns = _column_names(conn, "cameras")
    if "camera_role" not in camera_columns:
        conn.execute(
            "ALTER TABLE cameras ADD COLUMN camera_role TEXT NOT NULL DEFAULT 'support'"
        )

    from track_fraude_core.db.camera_roles import infer_camera_role

    rows = conn.execute(
        "SELECT id, camera_id, description, camera_role FROM cameras"
    ).fetchall()
    for row in rows:
        if str(row["camera_role"] or "support") != "support":
            continue
        role = infer_camera_role(
            camera_id=str(row["camera_id"]),
            description=str(row["description"] or ""),
        )
        conn.execute(
            "UPDATE cameras SET camera_role = ? WHERE id = ?",
            (role, int(row["id"])),
        )

    if not _table_exists(conn, "camera_zones"):
        conn.executescript(
            """
            CREATE TABLE camera_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_db_id INTEGER NOT NULL,
                zone_type TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                lane_id INTEGER,
                polygon_json TEXT NOT NULL,
                entry_vector_json TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (camera_db_id) REFERENCES cameras(id) ON DELETE CASCADE,
                UNIQUE (camera_db_id, zone_id)
            );
            """
        )


def _migrate_pipeline_and_review(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "pipeline_runs"):
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_db_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                current_phase TEXT NOT NULL DEFAULT '',
                current_camera TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                FOREIGN KEY (store_db_id) REFERENCES stores(id) ON DELETE CASCADE
            );
            """
        )

    if not _table_exists(conn, "alert_reviews"):
        conn.executescript(
            """
            CREATE TABLE alert_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_db_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                alert_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_review',
                reviewer_user_id INTEGER,
                note TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_db_id) REFERENCES stores(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewer_user_id) REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE (store_db_id, date, alert_id)
            );
            """
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
    if _table_exists(conn, "camera_zones"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_camera_zones_camera ON camera_zones(camera_db_id)"
        )
    if _table_exists(conn, "pipeline_runs"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_store ON pipeline_runs(store_db_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status)"
        )
    if _table_exists(conn, "alert_reviews"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_reviews_store_date "
            "ON alert_reviews(store_db_id, date)"
        )


def init_database(db_path: Path | str | None = None) -> Path:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    with get_connection(path) as conn:
        conn.executescript(SCHEMA)
        _migrate_legacy_schema(conn)
        _migrate_cameras_and_zones(conn)
        _migrate_pipeline_and_review(conn)
        _ensure_indexes(conn)
        conn.commit()
    return path
