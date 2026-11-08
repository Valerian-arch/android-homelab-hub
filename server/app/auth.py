"""Admin account, browser sessions, and login rate limiting."""

from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .crypto import hash_token
from .db import Database

SESSION_COOKIE = "hub_session"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Session:
    token_hash: str
    csrf_token: str


def validate_new_password(password: str, confirm: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return "Password is too long."
    if password != confirm:
        return "Passwords do not match."
    return None


class AuthStore:
    def __init__(self, db: Database, session_hours: int) -> None:
        self.db = db
        self.session_hours = session_hours

    # --- admin account ---
    def admin_exists(self) -> bool:
        with self.db.connect() as conn:
            return conn.execute("SELECT 1 FROM admin WHERE id = 1").fetchone() is not None

    def create_admin(self, password_hash: str) -> bool:
        """Create the single admin account. Returns False if it already exists."""
        try:
            with self.db.connect() as conn:
                conn.execute("INSERT INTO admin (id, password_hash) VALUES (1, ?)", (password_hash,))
        except sqlite3.IntegrityError:
            return False
        return True

    def get_admin_hash(self) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
        return row["password_hash"] if row else None

    # --- sessions ---
    def create_session(self) -> str:
        """Create a session and return the raw token for the cookie."""
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=self.session_hours)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now_iso(),))
            conn.execute(
                "INSERT INTO sessions (token_hash, csrf_token, expires_at) VALUES (?, ?, ?)",
                (hash_token(token), secrets.token_urlsafe(32), expires.isoformat(timespec="seconds")),
            )
        return token

    def get_session(self, token: str) -> Session | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT token_hash, csrf_token FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (hash_token(token), _now_iso()),
            ).fetchone()
        return Session(row["token_hash"], row["csrf_token"]) if row else None

    def delete_session(self, token: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


class LoginLimiter:
    """Locks out a client after too many failed logins within a time window."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 300) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = recent
        return recent

    def is_locked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
