"""Turning a saved file into text.

Extraction is best-effort by design. If Tesseract is not installed, or a PDF is
a pure scan, the file is still captured and queued for review with whatever text
was recovered - the operator types the rest. Losing the document because a
dependency is missing would be far worse than an empty text field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lbos.settings import Settings

TEXT_SUFFIXES = {".txt", ".md", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class ExtractedText:
    text: str
    method: str
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _read_plain(path: Path) -> ExtractedText:
    return ExtractedText(path.read_text(encoding="utf-8", errors="replace"), "plain")


def _read_pdf(path: Path) -> ExtractedText:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        return ExtractedText("", "pdf", ["pypdf is not installed."])

    try:
        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        return ExtractedText("", "pdf", [f"Could not read the PDF: {exc}"])

    text = "\n".join(parts).strip()
    warnings: list[str] = []
    if not text:
        warnings.append(
            "This PDF has no selectable text - it is probably a scan. "
            "Type the details on the review screen."
        )
    return ExtractedText(text, "pdf", warnings)


def _read_image(path: Path, settings: Settings) -> ExtractedText:
    if not settings.ocr_enabled:
        return ExtractedText("", "ocr", ["Reading photos is switched off (LBOS_OCR_ENABLED)."])

    try:
        import pytesseract
        from PIL import Image
    except ImportError:  # pragma: no cover - dependencies are declared
        return ExtractedText("", "ocr", ["Image reading libraries are not installed."])

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    try:
        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang=settings.ocr_lang)
    except Exception as exc:
        # Almost always "Tesseract is not installed or not in your PATH".
        return ExtractedText(
            "",
            "ocr",
            [
                "Could not read text from this photo. The photo is saved - type "
                f"the details on the review screen. ({type(exc).__name__}: {exc})"
            ],
        )

    text = text.strip()
    warnings = [] if text else ["No text was found in this photo."]
    return ExtractedText(text, "ocr", warnings)


def extract(path: Path, settings: Settings) -> ExtractedText:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _read_plain(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return _read_image(path, settings)
    return ExtractedText("", "unknown", [f"Unsupported file type: {suffix or 'none'}"])
