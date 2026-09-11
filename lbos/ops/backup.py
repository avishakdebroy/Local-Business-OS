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

import os
import shutil
import sqlite3
import sys
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


# --- Copying a backup off the machine ----------------------------------------
#
# A backup that lives only on the shop's one laptop protects against almost
# nothing: the realistic disasters are the laptop being stolen, dropped, or
# having its disk fail. In a town with slow internet, a pen drive is the channel
# that actually works, so it gets a button.


@dataclass
class RemovableDrive:
    path: Path
    label: str
    free_bytes: int


def removable_drives() -> list[RemovableDrive]:
    """Pen drives and memory cards currently plugged in."""
    found: list[RemovableDrive] = []

    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        import ctypes
        import string

        DRIVE_REMOVABLE = 2
        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        for index, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << index):
                continue
            root = f"{letter}:\\"
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) != DRIVE_REMOVABLE:
                continue
            try:
                found.append(
                    RemovableDrive(Path(root), root, shutil.disk_usage(root).free)
                )
            except OSError:
                continue
        return found

    # Linux and macOS mount removable media under these roots.
    for parent in (Path("/media"), Path("/run/media"), Path("/Volumes")):
        if not parent.exists():
            continue
        for candidate in parent.iterdir():
            targets = [candidate]
            if candidate.is_dir() and parent.name in ("media", "media"):
                targets += [c for c in candidate.iterdir() if c.is_dir()]
            for target in targets:
                if not target.is_dir():
                    continue
                try:
                    found.append(
                        RemovableDrive(target, target.name, shutil.disk_usage(target).free)
                    )
                except OSError:
                    continue
    return found


def copy_to_drive(settings: Settings, archive: Path, drive: Path) -> dict[str, Any]:
    """Copy one backup archive onto a removable drive. Never raises."""
    try:
        if not archive.is_file():
            return {"status": "error", "detail": "That backup file is no longer there."}
        if not drive.is_dir():
            return {"status": "error", "detail": "That drive is not plugged in any more."}

        free = shutil.disk_usage(drive).free
        size = archive.stat().st_size
        if free < size * 1.1:
            return {
                "status": "error",
                "detail": f"Not enough room on the drive: needs {size // 1024 // 1024} MB, "
                          f"has {free // 1024 // 1024} MB.",
            }

        folder = drive / "LocalBusinessOS-Backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / archive.name

        # Copy through a writable handle so the flush happens on a handle that
        # can actually be flushed: os.fsync() on Windows calls _commit(), which
        # needs the file open for writing and fails on a read-only one. A pen
        # drive is exactly where an unflushed write is lost when it is pulled
        # out, so the flush has to really happen before we say it is safe.
        with open(archive, "rb") as source, open(target, "wb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        shutil.copystat(archive, target)

        return {"status": "ok", "path": str(target), "size_bytes": size}
    except Exception as exc:
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def latest_archive(settings: Settings) -> Path | None:
    archives = sorted(
        settings.backups_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return archives[0] if archives else None
