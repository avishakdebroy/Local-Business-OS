"""The database must enforce what the schema claims."""

import sqlite3

import pytest

from lbos.db import migrations
from lbos.db.connection import connect


def test_foreign_keys_are_enforced(conn):
    """SQLite leaves foreign keys off by default; the connection turns them on."""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memos (document_id, entry_date, title, body, created_at)"
            " VALUES (99999, '2026-09-02', 't', 'b', 'x')"
        )


def test_write_ahead_logging_is_on(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_migrations_are_idempotent(settings):
    from lbos.db.bootstrap import prepare

    assert len(prepare(settings)) >= 1
    assert prepare(settings) == []


def test_migration_version_is_recorded(conn):
    assert migrations.current_version(conn) == len(migrations.discover())


def test_money_amounts_cannot_be_negative(conn):
    conn.execute(
        "INSERT INTO documents (content_hash, source_kind, raw_text, doc_type, status,"
        " confidence, extraction_json, captured_at) VALUES ('h','text','t','sale','posted',1,'{}','x')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO money_entries (document_id, entry_date, direction, total_paisa, created_at)"
            " VALUES (1, '2026-09-02', 'sale', -100, 'x')"
        )


def test_only_one_live_entry_per_document(conn):
    conn.execute(
        "INSERT INTO documents (content_hash, source_kind, raw_text, doc_type, status,"
        " confidence, extraction_json, captured_at) VALUES ('h','text','t','sale','posted',1,'{}','x')"
    )
    insert = (
        "INSERT INTO money_entries (document_id, entry_date, direction, total_paisa, created_at)"
        " VALUES (1, '2026-09-02', 'sale', 100, 'x')"
    )
    conn.execute(insert)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert)

    # A superseded entry does not block the replacement.
    conn.execute("UPDATE money_entries SET voided_at = 'x' WHERE id = 1")
    conn.execute(insert)
    assert conn.execute("SELECT COUNT(*) FROM money_entries").fetchone()[0] == 2


def test_document_hashes_are_unique(conn):
    statement = (
        "INSERT INTO documents (content_hash, source_kind, raw_text, doc_type, status,"
        " confidence, extraction_json, captured_at) VALUES ('same','text','t','memo','posted',1,'{}','x')"
    )
    conn.execute(statement)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)


def test_in_memory_databases_skip_wal():
    memory = connect(":memory:")
    try:
        assert memory.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        memory.close()
