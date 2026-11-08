"""Paired phones (device tokens), one-time pairing codes, and small settings."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .crypto import hash_token
from .db import Database

# No 0/O, 1/I/L: easy to read aloud or type.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
PAIRING_MINUTES = 10
DEFAULT_DEVICE_NAME = "Android phone"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    created_at: str
    last_seen_at: str | None


class DeviceStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- pairing codes ---
    def create_pairing_code(self) -> tuple[str, datetime]:
        """Return a new one-time code (formatted "ABCD-EFGH") and its expiry."""
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        expires = datetime.now(timezone.utc) + timedelta(minutes=PAIRING_MINUTES)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM pairing_codes WHERE expires_at <= ?", (_now_iso(),))
            conn.execute(
                "INSERT INTO pairing_codes (code_hash, expires_at) VALUES (?, ?)",
                (hash_token(code), expires.isoformat(timespec="seconds")),
            )
        return format_code(code), expires

    def redeem_pairing_code(self, code: str, device_name: str) -> str | None:
        """Consume a valid code and return a new device token, or None."""
        normalized = normalize_code(code)
        if len(normalized) != CODE_LENGTH:
            return None
        token = secrets.token_urlsafe(32)
        name = (device_name or "").strip()[:60] or DEFAULT_DEVICE_NAME
        with self.db.connect() as conn:
            # Delete-and-check is atomic, so a code can only be used once.
            cur = conn.execute(
                "DELETE FROM pairing_codes WHERE code_hash = ? AND expires_at > ?",
                (hash_token(normalized), _now_iso()),
            )
            if cur.rowcount != 1:
                return None
            conn.execute("INSERT INTO devices (name, token_hash) VALUES (?, ?)", (name, hash_token(token)))
        return token

    # --- devices ---
    def authenticate(self, token: str) -> Device | None:
        if not token:
            return None
        token_hash = hash_token(token)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, created_at, last_seen_at FROM devices WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE devices SET last_seen_at = datetime('now') WHERE id = ?", (row["id"],))
        return Device(row["id"], row["name"], row["created_at"], row["last_seen_at"])

    def list(self) -> list[Device]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id, name, created_at, last_seen_at FROM devices ORDER BY created_at").fetchall()
        return [Device(r["id"], r["name"], r["created_at"], r["last_seen_at"]) for r in rows]

    def revoke(self, device_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    # --- settings ---
    def get_setting(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
