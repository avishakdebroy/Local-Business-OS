"""Saving uploaded files and identifying documents by content.

Identity is the SHA-256 of the normalised source, which is what makes
re-uploading yesterday's receipt a no-op instead of double-counting it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lbos.domain.errors import ValidationError
from lbos.settings import Settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_SUFFIXES = {
    ".txt", ".md", ".csv", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
}

_WS = re.compile(r"\s+")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredFile:
    path: Path
    original_filename: str
    size_bytes: int
    sha256: str


def hash_text(text: str) -> str:
    """Stable identity for a text document, insensitive to whitespace churn."""
    normalised = _WS.sub(" ", unicodedata.normalize("NFKC", text or "")).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in ALLOWED_SUFFIXES else ""


def save_upload(settings: Settings, filename: str | None, data: bytes) -> StoredFile:
    """Write an upload under ``data/uploads`` with a generated, safe name."""
    if not data:
        raise ValidationError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    suffix = safe_suffix(filename)
    if not suffix:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise ValidationError(f"Unsupported file type. Allowed: {allowed}")

    settings.ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = settings.uploads_dir / f"{stamp}-{uuid4().hex[:12]}{suffix}"
    target.write_bytes(data)

    original = _UNSAFE.sub("_", Path(filename or "upload").name)[:120] or "upload"
    return StoredFile(
        path=target,
        original_filename=original,
        size_bytes=len(data),
        sha256=hash_bytes(data),
    )
