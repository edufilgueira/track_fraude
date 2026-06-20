from __future__ import annotations

import re


def adapt_sql_for_postgres(sql: str) -> str:
    adapted = re.sub(r"datetime\s*\(\s*'now'\s*\)", "now()", sql, flags=re.IGNORECASE)
    adapted = re.sub(r"\bactive\s*=\s*1\b", "active IS TRUE", adapted, flags=re.IGNORECASE)
    adapted = re.sub(r"\bactive\s*=\s*0\b", "active IS FALSE", adapted, flags=re.IGNORECASE)
    adapted = adapted.replace("?", "%s")
    return adapted


def should_returning_id(sql: str) -> bool:
    stripped = sql.lstrip().upper()
    return stripped.startswith("INSERT") and "RETURNING" not in stripped
