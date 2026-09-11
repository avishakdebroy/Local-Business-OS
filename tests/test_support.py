"""Support, repair and getting a backup off the machine."""

import json
import zipfile
from pathlib import Path

from lbos.ops import backup, support


def test_health_reports_a_sound_installation(conn, settings):
    report = support.health(settings)
    assert report["database"]["integrity"] == "ok"
    assert report["database"]["foreign_key_violations"] == 0
    assert report["database"]["schema_version"] == report["database"]["expected_schema_version"]
    assert support.problems(report) == []


def test_the_support_file_carries_no_secrets(settings):
    """It leaves the building over WhatsApp, so it must be safe to send."""
    secret = settings.model_copy(update={
        "smtp_password": "hunter2", "smtp_user": "owner@example.com",
        "report_email_to": "owner@example.com", "rclone_remote": "gdrive",
    })
    secret.ensure_dirs()
    from lbos.db.bootstrap import prepare
    prepare(secret)

    bundle = support.build_bundle(secret)
    blob = bundle.path.read_bytes()
    assert b"hunter2" not in blob
    assert b"owner@example.com" not in blob

    with zipfile.ZipFile(bundle.path) as archive:
        report = json.loads(archive.read("health.json"))
    assert report["settings"]["smtp_password"] == "<set>"
    assert report["settings"]["report_email_to"] == "<set>"


def test_the_support_file_is_small_enough_for_a_slow_connection(conn, settings):
    """A rural upload will never finish a multi-megabyte dump."""
    (settings.logs_dir / "lbos.log").write_bytes(b"x" * 5_000_000)
    bundle = support.build_bundle(settings)
    assert bundle.size_bytes < 200_000, "support file must stay sendable"
    assert "lbos-tail.log" in bundle.contents


def test_repair_is_safe_on_a_healthy_database(conn, settings):
    result = support.repair(settings)
    assert result["status"] == "ok"
    assert any("up to date" in step for step in result["steps"])


def test_repair_refuses_to_touch_a_missing_database(settings):
    result = support.repair(settings)
    assert result["status"] == "error"


def test_problems_are_described_in_plain_language():
    report = {
        "database": {"integrity": "ok", "foreign_key_violations": 2,
                     "schema_version": 1, "expected_schema_version": 2},
        "disk_free_mb": 100,
        "recent_jobs": [{"job_name": "nightly_backup", "status": "error",
                         "finished_at": "2026-09-10T03:00:00Z"}],
    }
    found = support.problems(report)
    assert any("Press Repair" in p for p in found)
    assert any("older than the program" in p for p in found)
    assert any("disk space" in p for p in found)
    assert any("nightly_backup" in p for p in found)


def test_a_backup_can_be_copied_to_a_pen_drive(conn, settings, tmp_path):
    archive = backup.run_backup(settings, include_uploads=True)
    assert archive.status == "ok"

    drive = tmp_path / "PENDRIVE"
    drive.mkdir()
    result = backup.copy_to_drive(settings, Path(archive.path), drive)
    assert result["status"] == "ok"

    copied = drive / "LocalBusinessOS-Backups" / Path(archive.path).name
    assert copied.is_file()
    with zipfile.ZipFile(copied) as z:
        assert "shop.db" in z.namelist()


def test_copying_to_a_drive_that_was_pulled_out_is_reported(conn, settings, tmp_path):
    archive = backup.run_backup(settings)
    result = backup.copy_to_drive(settings, Path(archive.path), tmp_path / "gone")
    assert result["status"] == "error"
    assert "not plugged in" in result["detail"]


def test_latest_archive_picks_the_newest(conn, settings):
    assert backup.latest_archive(settings) is None
    backup.run_backup(settings)
    second = backup.run_backup(settings, include_uploads=True)
    assert backup.latest_archive(settings).name == Path(second.path).name
