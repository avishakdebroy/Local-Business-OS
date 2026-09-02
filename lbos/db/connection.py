"""SQLite connection setup.

Every connection is configured the same way, because the defaults are wrong for
this application:

* ``foreign_keys`` is OFF by default in SQLite, which silently turns every
  REFERENCES clause into a comment. It is turned on here.
* ``journal_mode=WAL`` lets the background scheduler write a report while the
  operator is uploading a receipt, instead of one blocking the other.
* ``busy_timeout`` makes a contended write wait rather than fail instantly.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY_TIMEOUT_MS = 10_000


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a configured connection, creating the parent directory if needed."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        timeout=BUSY_TIMEOUT_MS / 1000,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
    # An in-memory database has no file to journal; WAL is meaningless there.
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a connection for the duration of one unit of work."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception.

    Ledger writes always span several tables; a partial write would leave the
    books inconsistent, so they all go through here.
    """
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def checkpoint(conn: sqlite3.Connection) -> None:
    """Fold the WAL back into the main database file."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
