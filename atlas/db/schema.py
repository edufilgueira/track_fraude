from __future__ import annotations

from pathlib import Path


def _schema_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "infra" / "postgres" / "schema_atlas.sql",
        Path.cwd() / "infra" / "postgres" / "schema_atlas.sql",
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise FileNotFoundError(
            "Schema Atlas não encontrado (infra/postgres/schema_atlas.sql)"
        )
    return path


def init_atlas_schema(postgres_url: str) -> None:
    import psycopg

    sql = _schema_path().read_text(encoding="utf-8")
    with psycopg.connect(postgres_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'atlas' AND table_name = 'workloads'
                """
            )
            if cur.fetchone() is None:
                cur.execute(sql)
        conn.commit()
