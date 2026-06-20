from __future__ import annotations

from track_fraude_core.db.database import DatabaseConfig
from track_fraude_core.db.dialect import adapt_sql_for_postgres


def test_database_config_from_postgres_url() -> None:
    config = DatabaseConfig.from_dsn(
        "postgresql://track_fraude:secret@localhost:5432/track_fraude"
    )
    assert config.is_postgres
    assert config.dsn.startswith("postgresql://")


def test_database_config_from_sqlite_path() -> None:
    config = DatabaseConfig.from_dsn("data/track_fraude.db")
    assert not config.is_postgres
    assert config.dsn.endswith("track_fraude.db")


def test_adapt_sql_for_postgres() -> None:
    sql = (
        "UPDATE pipeline_runs SET updated_at = datetime('now') "
        "WHERE id = ? AND active = 1"
    )
    adapted = adapt_sql_for_postgres(sql)
    assert "now()" in adapted
    assert "active IS TRUE" in adapted
    assert "%s" in adapted
    assert "?" not in adapted
