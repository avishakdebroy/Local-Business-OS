"""Taking entries in, from the text box or a file upload."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, Form, UploadFile

from lbos.api.deps import get_conn, get_settings
from lbos.api.templating import redirect
from lbos.capture import storage, text_extract
from lbos.domain.errors import ValidationError
from lbos.ledger import posting
from lbos.settings import Settings

router = APIRouter(tags=["capture"])


def _outcome(result) -> tuple[str, str, str]:
    """Where to send the operator next, and what to tell them."""
    if result.is_duplicate:
        return f"/review/{result.document_id}", result.message, "warn"
    if result.needs_review:
        return f"/review/{result.document_id}", result.message, "warn"
    return "/", f"Entry {result.document_id} recorded.", "ok"


@router.post("/capture/text")
def capture_text(
    text: str = Form(...),
    hint: str = Form("auto"),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    if not text.strip():
        return redirect("/", "Type something first.", "error")

    result = posting.capture(conn, settings, text=text, hint=hint, source_kind="text")
    path, message, kind = _outcome(result)
    return redirect(path, message, kind)


@router.post("/capture/file")
def capture_file(
    file: UploadFile = File(...),
    hint: str = Form("auto"),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    try:
        stored = storage.save_upload(settings, file.filename, file.file.read())
    except ValidationError as exc:
        return redirect("/", str(exc), "error")

    # The file is on disk before anything is read from it, so a failure to
    # extract text can never lose the receipt.
    extracted = text_extract.extract(stored.path, settings)
    result = posting.capture(
        conn,
        settings,
        text=extracted.text,
        hint=hint,
        source_kind="file",
        stored=stored,
        warnings=extracted.warnings,
    )
    path, message, kind = _outcome(result)
    return redirect(path, message, kind)
