"""Forward-only schema migrations.

Numbered ``.sql`` files in ``migrations/`` are applied in order and recorded in
``schema_migrations``. Shipping a schema change to a shop that already has data
means adding a file here; it never means editing an existing one.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from lbos.domain.periods import now_utc_iso

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FILENAME = re.compile(r"^(\d{3,})_([A-Za-z0-9_\-]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover(directory: Path | None = None) -> list[Migration]:
    folder = directory or MIGRATIONS_DIR
    found: list[Migration] = []
    for path in sorted(folder.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise ValueError(f"migration filename must be NNN_name.sql: {path.name}")
        found.append(Migration(int(match.group(1)), match.group(2), path))

    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise ValueError("duplicate migration version numbers")
    return sorted(found, key=lambda m: m.version)


def _ensure_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_registry(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def migrate(conn: sqlite3.Connection, directory: Path | None = None) -> list[Migration]:
    """Apply every migration newer than the recorded version. Returns those applied."""
    _ensure_registry(conn)
    applied_version = current_version(conn)
    pending = [m for m in discover(directory) if m.version > applied_version]

    for migration in pending:
        # executescript() commits any open transaction first, so each migration
        # is applied and recorded as its own unit.
        conn.executescript(migration.sql())
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now_utc_iso()),
        )
        conn.commit()

    return pending
