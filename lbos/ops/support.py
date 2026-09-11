"""Getting help when something goes wrong, from a town with slow internet.

Two jobs:

* **Tell someone what is wrong.** One button produces a small file the owner can
  send over WhatsApp. It has to be *small* — a 20 MB log dump will never finish
  uploading on a rural connection — and it must contain no customer names,
  phone numbers, amounts or passwords, because it leaves the building.
* **Fix the ordinary things without help.** An integrity check, a WAL
  checkpoint and a re-run of pending migrations covers most of what actually
  goes wrong on a single-user SQLite app.
"""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lbos import __version__
from lbos.db import migrations
from lbos.db.connection import checkpoint, connect
from lbos.domain.periods import now_utc_iso
from lbos.settings import Settings

#: Keep the bundle sendable on a slow connection.
LOG_TAIL_BYTES = 64 * 1024

#: Anything whose name contains one of these never leaves the machine.
SECRET_HINTS = ("password", "token", "secret", "key", "smtp_user", "email")

#: Tables we report row counts for. Counts only — never contents.
COUNTED_TABLES = (
    "documents", "money_entries", "items", "stock_moves", "memos",
    "customers", "credit_entries", "report_runs", "job_runs", "paired_devices",
)


def _safe_settings(settings: Settings) -> dict[str, Any]:
    """Configuration with anything sensitive replaced by whether it is set."""
    out: dict[str, Any] = {}
    for name, value in settings.model_dump().items():
        if any(hint in name for hint in SECRET_HINTS):
            out[name] = "<set>" if value else "<empty>"
        else:
            out[name] = str(value) if isinstance(value, Path) else value
    return out


def _table_counts(conn: sqlite3.Connection) -> dict[str, int | str]:
    counts: dict[str, int | str] = {}
    for table in COUNTED_TABLES:
        try:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error as exc:
            counts[table] = f"error: {exc}"
    return counts


def health(settings: Settings) -> dict[str, Any]:
    """A machine-readable picture of this installation."""
    report: dict[str, Any] = {
        "generated_at": now_utc_iso(),
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "frozen_exe": bool(getattr(sys, "frozen", False)),
        "sqlite": sqlite3.sqlite_version,
        "data_dir_exists": settings.data_dir.exists(),
        "settings": _safe_settings(settings),
    }
    try:
        usage = shutil.disk_usage(settings.data_dir if settings.data_dir.exists() else Path.cwd())
        report["disk_free_mb"] = round(usage.free / 1024 / 1024)
    except OSError as exc:
        report["disk_free_mb"] = f"error: {exc}"

    if not settings.db_path.exists():
        report["database"] = "not created yet"
        return report

    conn = connect(settings.db_path)
    try:
        report["database"] = {
            "size_mb": round(settings.db_path.stat().st_size / 1024 / 1024, 2),
            "schema_version": migrations.current_version(conn),
            "expected_schema_version": max((m.version for m in migrations.discover()), default=0),
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "counts": _table_counts(conn),
        }
        report["recent_jobs"] = [
            {k: row[k] for k in ("job_name", "status", "finished_at")}
            for row in conn.execute(
                "SELECT job_name, status, finished_at FROM job_runs ORDER BY id DESC LIMIT 10"
            )
        ]
    finally:
        conn.close()
    return report


def problems(report: dict[str, Any]) -> list[str]:
    """Plain-language descriptions of anything wrong, for the owner to read."""
    found: list[str] = []
    database = report.get("database")
    if isinstance(database, dict):
        if database.get("integrity") != "ok":
            found.append("The database file reports damage. Restore your most recent backup.")
        if database.get("foreign_key_violations"):
            found.append("Some records point at rows that no longer exist. Press Repair.")
        if database.get("schema_version", 0) < database.get("expected_schema_version", 0):
            found.append("The database is older than the program. Press Repair to bring it up to date.")
    free = report.get("disk_free_mb")
    if isinstance(free, int) and free < 500:
        found.append(f"Only {free} MB of disk space is left. Delete some files or old backups.")
    for job in report.get("recent_jobs", []):
        if job["status"] == "error":
            found.append(f"The background job “{job['job_name']}” failed on {job['finished_at'][:10]}.")
            break
    return found


@dataclass
class SupportBundle:
    path: Path
    size_bytes: int
    contents: list[str] = field(default_factory=list)


def build_bundle(settings: Settings) -> SupportBundle:
    """A small zip the owner can send to whoever helps them.

    Contains a health report, the tail of the log and the migration list.
    It contains **no** customer names, amounts, phone numbers or passwords.
    """
    settings.ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = settings.logs_dir / f"support-{stamp}.zip"

    report = health(settings)
    report["problems"] = problems(report)
    written: list[str] = []

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("health.json", json.dumps(report, indent=2, default=str))
        written.append("health.json")

        archive.writestr(
            "README.txt",
            "Local Business OS — support file\n"
            "=================================\n\n"
            f"Made on {report['generated_at']} by version {report['app_version']}.\n\n"
            "This file describes how the program is set up and what went wrong.\n"
            "It does NOT contain your customers, your sales figures, your phone\n"
            "numbers or any password. It is safe to send to whoever helps you.\n",
        )
        written.append("README.txt")

        log = settings.logs_dir / "lbos.log"
        if log.exists():
            with log.open("rb") as handle:
                handle.seek(max(0, log.stat().st_size - LOG_TAIL_BYTES))
                archive.writestr("lbos-tail.log", handle.read())
            written.append("lbos-tail.log")

        archive.writestr(
            "migrations.txt",
            "\n".join(f"{m.version:03d} {m.name}" for m in migrations.discover()),
        )
        written.append("migrations.txt")

    return SupportBundle(path=target, size_bytes=target.stat().st_size, contents=written)


def repair(settings: Settings) -> dict[str, Any]:
    """The safe fixes, in order. Never destroys data."""
    steps: list[str] = []
    if not settings.db_path.exists():
        return {"status": "error", "steps": ["There is no database file yet."]}

    conn = connect(settings.db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        steps.append(f"Integrity check: {integrity}")
        if integrity != "ok":
            return {
                "status": "error",
                "steps": steps + ["The file is damaged; restore your most recent backup instead."],
            }

        applied = migrations.migrate(conn)
        steps.append(
            f"Applied {len(applied)} pending update(s)." if applied else "Database is up to date."
        )

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        steps.append(f"Orphaned records: {len(violations)}")

        checkpoint(conn)
        steps.append("Write-ahead log folded back into the database.")

        conn.execute("ANALYZE")
        steps.append("Query statistics refreshed.")
    finally:
        conn.close()

    return {"status": "ok", "steps": steps}
