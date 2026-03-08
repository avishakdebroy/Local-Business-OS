from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import zipfile

from app.config import settings


def run_backup() -> dict:
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_name = f"backup-{ts}.zip"
    backup_path = settings.app_data_dir / "backups" / backup_name

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if settings.app_db_path.exists():
            zf.write(settings.app_db_path, arcname="shop.db")

        uploads = settings.app_data_dir / "uploads"
        reports = settings.app_data_dir / "reports"

        if uploads.exists():
            for p in uploads.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=f"uploads/{p.name}")

        if reports.exists():
            for p in reports.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=f"reports/{p.name}")

    cloud_status = "skipped: rclone not configured"
    if settings.rclone_remote:
        target = f"{settings.rclone_remote}:{settings.rclone_path}"
        try:
            subprocess.run(
                ["rclone", "copy", str(backup_path), target],
                check=True,
                capture_output=True,
                text=True,
            )
            cloud_status = f"uploaded to {target}"
        except Exception as exc:
            cloud_status = f"upload failed: {exc}"

    return {
        "status": "ok",
        "backup_path": str(backup_path),
        "cloud_status": cloud_status,
    }
