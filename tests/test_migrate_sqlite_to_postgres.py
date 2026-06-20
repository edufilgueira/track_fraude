from __future__ import annotations

import sqlite3

from tools.migrate_sqlite_to_postgres import _convert_value, _row_to_tuple


def test_convert_sqlite_int_to_postgres_bool() -> None:
    assert _convert_value("active", 1, {"active"}) is True
    assert _convert_value("active", 0, {"active"}) is False
    assert _convert_value("name", "Loja", {"active"}) == "Loja"


def test_row_to_tuple_converts_boolean_columns() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE t (id INTEGER, active INTEGER, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 1, 'x')")
    row = conn.execute("SELECT id, active, name FROM t").fetchone()
    assert _row_to_tuple(row, ["id", "active", "name"], {"active"}) == (1, True, "x")
