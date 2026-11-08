"""Storage for configured services."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .db import Database


@dataclass
class Service:
    id: int
    name: str
    type: str
    category: str = ""
    link_url: str = ""
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    secrets_enc: str | None = None
    """Encrypted credentials. Never send this to clients."""


def _from_row(row: sqlite3.Row) -> Service:
    return Service(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        category=row["category"],
        link_url=row["link_url"],
        enabled=bool(row["enabled"]),
        config=json.loads(row["config_json"]),
        secrets_enc=row["secrets_enc"],
    )


class ServiceStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, enabled_only: bool = False) -> list[Service]:
        sql = "SELECT * FROM services"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY category COLLATE NOCASE, name COLLATE NOCASE"
        with self.db.connect() as conn:
            return [_from_row(r) for r in conn.execute(sql).fetchall()]

    def get(self, service_id: int) -> Service | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        return _from_row(row) if row else None

    def create(
        self, *, name: str, type: str, category: str, link_url: str, enabled: bool,
        config: dict[str, Any], secrets_enc: str | None,
    ) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO services (name, type, category, link_url, enabled, config_json, secrets_enc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, type, category, link_url, int(enabled), json.dumps(config), secrets_enc),
            )
            return int(cur.lastrowid)

    def update(
        self, service_id: int, *, name: str, category: str, link_url: str, enabled: bool,
        config: dict[str, Any], secrets_enc: str | None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE services SET name = ?, category = ?, link_url = ?, enabled = ?,"
                " config_json = ?, secrets_enc = ?, updated_at = datetime('now') WHERE id = ?",
                (name, category, link_url, int(enabled), json.dumps(config), secrets_enc, service_id),
            )

    def delete(self, service_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
