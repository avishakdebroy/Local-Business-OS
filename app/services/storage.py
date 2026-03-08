from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from datetime import datetime

from fastapi import UploadFile

from app.config import settings


def ensure_app_dirs() -> None:
    (settings.app_data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (settings.app_data_dir / "reports").mkdir(parents=True, exist_ok=True)
    (settings.app_data_dir / "backups").mkdir(parents=True, exist_ok=True)


def save_upload(file: UploadFile) -> Path:
    ensure_app_dirs()
    ext = Path(file.filename or "upload.bin").suffix
    safe_ext = ext if ext else ".bin"
    name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex}{safe_ext}"
    target = settings.app_data_dir / "uploads" / name
    content = file.file.read()
    target.write_bytes(content)
    return target
