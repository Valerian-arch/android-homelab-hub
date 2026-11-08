"""Admin account, browser sessions, recovery codes, and login rate limiting."""

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

LOGIN_MAX_FAILURES = 3
LOGIN_LOCKOUT_SECONDS = 15 * 60

RECOVERY_CODE_COUNT = 5
# No 0/O, 1/I/L. 10 characters = about 49 bits each; combined with the login lockout, not guessable.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_password() -> str:
    """Random first-run admin password (about 96 bits)."""
    return secrets.token_urlsafe(12)


def _normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


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

    def create_admin(self, password_hash: str, must_change: bool = True) -> bool:
        """Create the single admin account. Returns False if it already exists."""
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO admin (id, password_hash, must_change) VALUES (1, ?, ?)",
                    (password_hash, int(must_change)),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def get_admin_hash(self) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
        return row["password_hash"] if row else None

    def must_change_password(self) -> bool:
        with self.db.connect() as conn:
            row = conn.execute("SELECT must_change FROM admin WHERE id = 1").fetchone()
        return bool(row and row["must_change"])

    def set_password(self, password_hash: str, must_change: bool = False) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE admin SET password_hash = ?, must_change = ? WHERE id = 1",
                (password_hash, int(must_change)),
            )

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

    def delete_other_sessions(self, keep_token_hash: str | None = None) -> None:
        """Log out everywhere, optionally keeping one session (the current one)."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash IS NOT ?", (keep_token_hash,))

    # --- recovery codes ---
    def generate_recovery_codes(self) -> list[str]:
        """Replace all recovery codes with new ones; return them (shown once)."""
        codes = []
        for _ in range(RECOVERY_CODE_COUNT):
            raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
            codes.append(f"{raw[:5]}-{raw[5:]}")
        with self.db.connect() as conn:
            conn.execute("DELETE FROM recovery_codes")
            conn.executemany(
                "INSERT INTO recovery_codes (code_hash) VALUES (?)",
                [(hash_token(_normalize_recovery_code(c)),) for c in codes],
            )
        return codes

    def recovery_codes_left(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM recovery_codes").fetchone()[0])

    def use_recovery_code(self, code: str) -> bool:
        normalized = _normalize_recovery_code(code)
        if len(normalized) != 10:
            return False
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM recovery_codes WHERE code_hash = ?", (hash_token(normalized),))
            return cur.rowcount == 1


class LoginLimiter:
    """Locks out a client after too many failed attempts within a time window.

    Attempts are recorded *before* the (slow) password check, so a burst of
    parallel requests cannot slip past the limit. A successful attempt clears them.
    """

    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES, window_seconds: float = LOGIN_LOCKOUT_SECONDS) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        recent = [t for t in self._attempts.get(key, []) if now - t < self.window]
        self._attempts[key] = recent
        return recent

    def is_locked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def try_acquire(self, key: str) -> bool:
        """Record an attempt. Returns False (and records nothing) if already locked out."""
        recent = self._recent(key)
        if len(recent) >= self.max_failures:
            return False
        recent.append(time.monotonic())
        return True

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
