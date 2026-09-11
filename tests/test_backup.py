"""Backups must be consistent, bounded in size, and never crash the caller."""

import sqlite3
import zipfile

from lbos.ledger import repositories as repo
from lbos.ops.backup import DB_PREFIX, prune, run_backup, snapshot_database


def test_a_snapshot_is_a_usable_database(conn, settings, tmp_path):
    repo.insert_document(
        conn, content_hash="h", source_kind="text", doc_type="memo", status="posted",
        confidence=1.0, raw_text="hello", extraction={}, extractor="test",
    )
    conn.commit()

    target = tmp_path / "snapshot.db"
    snapshot_database(settings.db_path, target)

    restored = sqlite3.connect(target)
    try:
        assert restored.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        restored.close()


def test_a_snapshot_is_consistent_while_writes_are_in_flight(conn, settings, tmp_path):
    """A plain file copy can capture a torn database; the backup API cannot."""
    for index in range(50):
        repo.insert_document(
            conn, content_hash=f"h{index}", source_kind="text", doc_type="memo",
            status="posted", confidence=1.0, raw_text="x", extraction={}, extractor="t",
        )
    conn.commit()
    conn.execute("BEGIN")  # an open write transaction, uncommitted
    conn.execute(
        "INSERT INTO documents (content_hash, source_kind, raw_text, doc_type, status,"
        " confidence, extraction_json, captured_at) VALUES ('pending','text','x','memo','posted',1,'{}','x')"
    )

    target = tmp_path / "snapshot.db"
    snapshot_database(settings.db_path, target)
    conn.rollback()

    restored = sqlite3.connect(target)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 50
    finally:
        restored.close()


def test_the_nightly_backup_excludes_uploads(conn, settings):
    settings.ensure_dirs()
    (settings.uploads_dir / "receipt.jpg").write_bytes(b"x" * 2048)

    nightly = run_backup(settings, include_uploads=False)
    assert nightly.status == "ok"
    assert not any(n.startswith("uploads/") for n in zipfile.ZipFile(nightly.path).namelist())

    full = run_backup(settings, include_uploads=True)
    assert "uploads/receipt.jpg" in zipfile.ZipFile(full.path).namelist()


def test_old_backups_are_pruned(settings):
    settings.ensure_dirs()
    for index in range(8):
        path = settings.backups_dir / f"{DB_PREFIX}2026010{index}-000000.zip"
        path.write_bytes(b"x")
        import os
        os.utime(path, (index, index))

    removed = prune(settings.backups_dir, DB_PREFIX, keep=3)
    assert len(removed) == 5
    assert len(list(settings.backups_dir.glob(f"{DB_PREFIX}*.zip"))) == 3


def test_backups_stay_bounded_over_many_nights(conn, settings):
    settings.ensure_dirs()
    (settings.uploads_dir / "big.jpg").write_bytes(b"x" * 100_000)
    settings_keep = settings.model_copy(update={"backup_keep": 3})

    for _ in range(6):
        assert run_backup(settings_keep, include_uploads=False).status == "ok"

    archives = list(settings.backups_dir.glob("*.zip"))
    assert len(archives) == 3
    assert sum(p.stat().st_size for p in archives) < 100_000


def test_a_backup_failure_is_reported_not_raised(settings, monkeypatch):
    monkeypatch.setattr(
        "lbos.ops.backup.snapshot_database",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    settings.ensure_dirs()
    settings.db_path.write_bytes(b"")
    result = run_backup(settings)
    assert result.status == "error"
    assert "disk full" in result.error


def test_offsite_copy_is_skipped_when_not_configured(conn, settings):
    result = run_backup(settings)
    assert result.offsite_status == "skipped"
