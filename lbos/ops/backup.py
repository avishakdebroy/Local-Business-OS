"""Backups.

Two things the naive version of this gets wrong, and how they are handled:

* Zipping ``shop.db`` while the app is writing can capture a torn file. SQLite's
  online backup API is used instead, which produces a consistent snapshot even
  under concurrent writes.
* Re-zipping every uploaded photo every night fills the disk. The nightly backup
  carries the database and reports only; uploads go into a separate weekly
  archive, and both are pruned to a retention limit.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lbos.settings import Settings

DB_PREFIX = "db-"
FULL_PREFIX = "full-"


@dataclass
class BackupResult:
    status: str
    path: str | None
    size_bytes: int
    kind: str
    offsite_status: str = "skipped"
    offsite_detail: str = ""
    pruned: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def snapshot_database(db_path: Path, target: Path) -> None:
    """Copy the database using SQLite's online backup API.

    Unlike a file copy this is safe while the application is running.
    """
    source = sqlite3.connect(str(db_path))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _add_tree(archive: zipfile.ZipFile, folder: Path, arc_prefix: str) -> None:
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=f"{arc_prefix}/{path.relative_to(folder)}")


def prune(folder: Path, prefix: str, keep: int) -> list[str]:
    """Delete all but the newest ``keep`` archives with this prefix."""
    archives = sorted(
        folder.glob(f"{prefix}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    removed: list[str] = []
    for path in archives[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def _push_offsite(settings: Settings, path: Path) -> tuple[str, str]:
    if not settings.rclone_remote:
        return "skipped", "No offsite remote is configured."
    target = f"{settings.rclone_remote}:{settings.rclone_path}"
    try:
        subprocess.run(
            ["rclone", "copy", str(path), target],
            check=True, capture_output=True, text=True, timeout=1800,
        )
    except FileNotFoundError:
        return "failed", "rclone is not installed or not on PATH."
    except subprocess.CalledProcessError as exc:
        return "failed", (exc.stderr or exc.stdout or str(exc)).strip()[:500]
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"
    return "sent", f"Copied to {target}."


def run_backup(settings: Settings, include_uploads: bool = False) -> BackupResult:
    """Write one backup archive. Never raises."""
    kind = "full" if include_uploads else "database"
    prefix = FULL_PREFIX if include_uploads else DB_PREFIX
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    try:
        settings.ensure_dirs()
        # Two backups inside the same second must not overwrite one another.
        archive_path = settings.backups_dir / f"{prefix}{stamp}.zip"
        attempt = 1
        while archive_path.exists():
            archive_path = settings.backups_dir / f"{prefix}{stamp}-{attempt}.zip"
            attempt += 1

        with tempfile.TemporaryDirectory() as work:
            snapshot = Path(work) / "shop.db"
            if settings.db_path.exists():
                snapshot_database(settings.db_path, snapshot)

            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                if snapshot.exists():
                    archive.write(snapshot, arcname="shop.db")
                _add_tree(archive, settings.reports_dir, "reports")
                if include_uploads:
                    _add_tree(archive, settings.uploads_dir, "uploads")

        offsite_status, offsite_detail = _push_offsite(settings, archive_path)
        pruned = prune(settings.backups_dir, prefix, settings.backup_keep)

        return BackupResult(
            status="ok",
            path=str(archive_path),
            size_bytes=archive_path.stat().st_size,
            kind=kind,
            offsite_status=offsite_status,
            offsite_detail=offsite_detail,
            pruned=pruned,
        )
    except Exception as exc:
        return BackupResult(
            status="error", path=None, size_bytes=0, kind=kind,
            error=f"{type(exc).__name__}: {exc}",
        )


def restore_preview(archive_path: Path) -> list[str]:
    """List what an archive contains, so a restore is never a blind operation."""
    with zipfile.ZipFile(archive_path) as archive:
        return archive.namelist()


def free_space_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free
