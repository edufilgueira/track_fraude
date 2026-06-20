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


def test_copy_table_intersects_columns(monkeypatch) -> None:
    import tools.migrate_sqlite_to_postgres as migrate

    sqlite_conn = sqlite3.connect(":memory:")
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, keep TEXT, legacy TEXT)")
    sqlite_conn.execute("INSERT INTO demo (id, keep, legacy) VALUES (1, 'ok', 'drop')")
    sqlite_conn.commit()

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self.last_sql = sql
            self.last_params = params

        def fetchall(self):
            if "information_schema.columns" in self.last_sql:
                return [("id",), ("keep",)]
            return []

        def executemany(self, sql, payload):
            assert "legacy" not in sql
            assert payload == [(1, "ok")]

    class FakePgConn:
        def cursor(self):
            return FakeCursor()

    copied = migrate._copy_table(sqlite_conn, FakePgConn(), "demo")
    assert copied == 1
