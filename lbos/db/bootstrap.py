"""One entry point that makes an installation ready to use."""

from __future__ import annotations

import sqlite3

from lbos.db import migrations
from lbos.db.connection import connect
from lbos.settings import Settings


def prepare(settings: Settings) -> list[migrations.Migration]:
    """Create data directories and bring the database schema up to date."""
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    try:
        return migrations.migrate(conn)
    finally:
        conn.close()


def open_db(settings: Settings) -> sqlite3.Connection:
    return connect(settings.db_path)
