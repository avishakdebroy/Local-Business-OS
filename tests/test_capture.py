"""Files must always survive, whatever happens when they are read."""

import pytest

from lbos.capture import storage, text_extract
from lbos.domain.errors import ValidationError


def test_identical_text_hashes_identically():
    assert storage.hash_text("Total 500") == storage.hash_text("  total   500  ")


def test_different_text_hashes_differently():
    assert storage.hash_text("Total 500") != storage.hash_text("Total 501")


def test_uploads_get_a_generated_safe_name(settings):
    stored = storage.save_upload(settings, "../../evil name.jpg", b"data")
    assert stored.path.parent == settings.uploads_dir
    assert stored.path.suffix == ".jpg"
    assert ".." not in stored.path.name
    assert stored.original_filename == "evil_name.jpg"


def test_unsupported_file_types_are_refused(settings):
    with pytest.raises(ValidationError, match="Unsupported"):
        storage.save_upload(settings, "payload.exe", b"MZ")


def test_empty_uploads_are_refused(settings):
    with pytest.raises(ValidationError, match="empty"):
        storage.save_upload(settings, "blank.jpg", b"")


def test_oversized_uploads_are_refused(settings):
    with pytest.raises(ValidationError, match="larger than"):
        storage.save_upload(settings, "huge.jpg", b"x" * (storage.MAX_UPLOAD_BYTES + 1))


def test_plain_text_is_read(settings, tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Total 500 taka", encoding="utf-8")
    assert text_extract.extract(path, settings).text.strip() == "Total 500 taka"


def test_a_photo_with_ocr_off_still_returns_a_result(settings, tmp_path):
    path = tmp_path / "receipt.jpg"
    path.write_bytes(b"not really a jpeg")
    result = text_extract.extract(path, settings)
    assert result.is_empty
    assert result.warnings  # the operator is told why, rather than getting an error


def test_a_missing_tesseract_does_not_raise(settings, tmp_path):
    ocr_on = settings.model_copy(update={"ocr_enabled": True, "tesseract_cmd": "/nonexistent"})
    path = tmp_path / "receipt.png"
    path.write_bytes(b"\x89PNG not really")
    result = text_extract.extract(path, ocr_on)
    assert result.is_empty
    assert any("review screen" in w or "libraries" in w for w in result.warnings)


def test_an_unreadable_pdf_is_reported_not_raised(settings, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 broken")
    result = text_extract.extract(path, settings)
    assert result.is_empty
    assert result.warnings
