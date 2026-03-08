from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path

from app.config import settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    file_path TEXT,
    raw_text TEXT NOT NULL,
    parsed_json TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    receipt_date TEXT,
    vendor TEXT,
    total_amount REAL,
    tax_amount REAL,
    category TEXT,
    payment_method TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE,
    name TEXT NOT NULL,
    unit TEXT DEFAULT 'pcs',
    current_qty REAL NOT NULL DEFAULT 0,
    reorder_level REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    document_id INTEGER,
    move_type TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_cost REAL,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES inventory_items(id),
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    title TEXT,
    body TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    report_path TEXT,
    summary_json TEXT,
    email_status TEXT,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(settings.app_db_path), check_same_thread=False)


def ensure_db_parent() -> None:
    settings.app_db_path.parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_db_parent()
    with _connect() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn() -> sqlite3.Connection:
    ensure_db_parent()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
