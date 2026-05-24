from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from track_fraude_core.db.connection import get_connection


@dataclass
class UserRecord:
    id: int
    username: str
    display_name: str
    active: bool


class UserRepository:
    def __init__(self, db_path) -> None:
        self.db_path = db_path

    def _conn(self):
        return get_connection(self.db_path)

    @staticmethod
    def hash_password(password: str, salt: str | None = None) -> str:
        salt_value = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_value.encode("utf-8"),
            100_000,
        ).hex()
        return f"{salt_value}${digest}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        salt, digest = stored_hash.split("$", 1)
        check = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()
        return secrets.compare_digest(digest, check)

    def get_by_username(self, username: str) -> tuple[UserRecord, str] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if not row:
            return None
        user = UserRecord(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or row["username"]),
            active=bool(row["active"]),
        )
        return user, str(row["password_hash"])

    def list_users(self) -> list[UserRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [
            UserRecord(
                id=int(row["id"]),
                username=str(row["username"]),
                display_name=str(row["display_name"] or row["username"]),
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str = "",
        active: bool = True,
    ) -> UserRecord:
        password_hash = self.hash_password(password)
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, display_name, active)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username.strip(),
                    password_hash,
                    display_name.strip() or username.strip(),
                    1 if active else 0,
                ),
            )
            conn.commit()
            user_id = int(cursor.lastrowid)
        user = self.get_by_id(user_id)
        assert user is not None
        return user

    def get_by_id(self, user_id: int) -> UserRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return UserRecord(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or row["username"]),
            active=bool(row["active"]),
        )

    def count_users(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        return int(row["total"]) if row else 0

    def seed_admin(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
    ) -> None:
        if self.count_users() > 0:
            return
        self.create_user(
            username=username,
            password=password,
            display_name=display_name,
        )

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        found = self.get_by_username(username)
        if not found:
            return None
        user, password_hash = found
        if not user.active:
            return None
        if not self.verify_password(password, password_hash):
            return None
        return user
