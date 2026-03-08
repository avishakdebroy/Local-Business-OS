from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from PIL import Image
import pytesseract

from app.config import settings


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        parts: list[str] = []
        reader = PdfReader(str(path))
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        image = Image.open(path)
        return pytesseract.image_to_string(image, lang=settings.ocr_lang).strip()

    return ""
