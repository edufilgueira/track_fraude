from __future__ import annotations

import sqlite3
from pathlib import Path

from track_fraude_core.db.connection import get_connection, init_database
from track_fraude_core.db import GroupRepository, StoreRepository


LEGACY_SCHEMA = """
CREATE TABLE stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    ocr_sample_interval_sec INTEGER NOT NULL DEFAULT 30,
    ocr_min_confidence REAL NOT NULL DEFAULT 0.5,
    pos_match_delta_sec INTEGER NOT NULL DEFAULT 60,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE cameras (
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
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def test_migrate_legacy_database_without_group_db_id(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO stores (store_id, name) VALUES (?, ?)",
        ("LOJA-01", "Loja antiga"),
    )
    conn.commit()
    conn.close()

    init_database(db_path)

    store_repo = StoreRepository(db_path)
    group_repo = GroupRepository(db_path)

    store = store_repo.get_store_by_code("LOJA-01")
    assert store is not None
    assert store.group_db_id > 0
    assert store.street == ""

    default_group = group_repo.get_group(store.group_db_id)
    assert default_group is not None
    assert default_group.group_code == "default"

    with get_connection(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stores)")}
    assert "group_db_id" in columns
    assert "street" in columns
    assert "r1_min_checkout_duration_sec" in columns
    assert "t_return_sec" in columns
    assert "r5_cancelled_delta_sec" in columns
    assert "buffer_before_sec" in columns
    assert "checkout_buffer_after_sec" in columns


def test_new_store_gets_alert_rule_defaults(tmp_path: Path):
    db_path = tmp_path / "rules_defaults.db"
    init_database(db_path)
    group_repo = GroupRepository(db_path)
    store_repo = StoreRepository(db_path)
    group = group_repo.create_group(group_code="test", name="Test")
    store = store_repo.create_store(group_db_id=group.id, store_id="LOJA-X", name="Loja X")
    assert store.r1_min_checkout_duration_sec == 20
    assert store.pos_match_delta_sec == 20
    assert store.t_return_sec == 1800
    assert store.r5_cancelled_delta_sec == 60
    assert store.buffer_before_sec == 20
    assert store.buffer_after_sec == 20
    assert store.checkout_buffer_before_sec == 5
    assert store.checkout_buffer_after_sec == 5
