from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from track_fraude_core.db.connection import get_connection, init_database
from track_fraude_core.db.database import DatabaseConfig, resolve_database

REVIEW_STATUS_PENDING = "pending_review"
REVIEW_STATUS_CONFIRMED = "confirmed"
REVIEW_STATUS_DISMISSED = "dismissed"

REVIEW_STATUSES = frozenset(
    {REVIEW_STATUS_PENDING, REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_DISMISSED}
)


@dataclass(frozen=True)
class AlertReviewRecord:
    id: int
    store_db_id: int
    date: str
    alert_id: str
    status: str
    reviewer_user_id: int | None
    note: str
    reviewed_at: str | None


class ReviewRepository:
    def __init__(self, db: DatabaseConfig | Path | str | None = None) -> None:
        self.db = resolve_database(db)
        init_database(self.db)

    def _conn(self):
        return get_connection(self.db)

    def get_decision(
        self, store_db_id: int, date: str, alert_id: str
    ) -> AlertReviewRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM alert_reviews
                WHERE store_db_id = ? AND date = ? AND alert_id = ?
                """,
                (store_db_id, date, alert_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_decisions_for_date(
        self, store_db_id: int, date: str
    ) -> dict[str, AlertReviewRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM alert_reviews
                WHERE store_db_id = ? AND date = ?
                """,
                (store_db_id, date),
            ).fetchall()
        return {str(row["alert_id"]): self._row_to_record(row) for row in rows}

    def save_decision(
        self,
        *,
        store_db_id: int,
        date: str,
        alert_id: str,
        status: str,
        reviewer_user_id: int | None,
        note: str = "",
    ) -> AlertReviewRecord:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Status inválido: {status!r}")

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO alert_reviews (
                    store_db_id, date, alert_id, status,
                    reviewer_user_id, note, reviewed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(store_db_id, date, alert_id) DO UPDATE SET
                    status = excluded.status,
                    reviewer_user_id = excluded.reviewer_user_id,
                    note = excluded.note,
                    reviewed_at = datetime('now'),
                    updated_at = datetime('now')
                """,
                (store_db_id, date, alert_id, status, reviewer_user_id, note.strip()),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT * FROM alert_reviews
                WHERE store_db_id = ? AND date = ? AND alert_id = ?
                """,
                (store_db_id, date, alert_id),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row) -> AlertReviewRecord:
        return AlertReviewRecord(
            id=int(row["id"]),
            store_db_id=int(row["store_db_id"]),
            date=str(row["date"]),
            alert_id=str(row["alert_id"]),
            status=str(row["status"]),
            reviewer_user_id=int(row["reviewer_user_id"])
            if row["reviewer_user_id"] is not None
            else None,
            note=str(row["note"] or ""),
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
        )
