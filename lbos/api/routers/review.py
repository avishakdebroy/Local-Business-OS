"""The review screen: where a proposal becomes a ledger entry."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from lbos.api.deps import get_conn, get_settings
from lbos.api.forms import fields_for
from lbos.api.routers.common import context
from lbos.api.templating import redirect, templates
from lbos.capture.text_extract import IMAGE_SUFFIXES
from lbos.domain.entities import DOC_TYPE_LABELS, PAYMENT_METHODS
from lbos.domain.errors import ConflictError, NotFoundError, ValidationError
from lbos.domain.periods import iso, local_today
from lbos.interpretation.vocabulary import CATEGORY_WORDS
from lbos.ledger import posting
from lbos.ledger import repositories as repo
from lbos.settings import Settings

router = APIRouter(tags=["review"])

CATEGORIES = sorted(set(CATEGORY_WORDS.values()))
TYPE_OPTIONS = [(value, label) for value, label in DOC_TYPE_LABELS.items()]

BLANK_STOCK_LINE = {
    "name": "", "qty_milli": 0, "unit": "pcs", "direction": "", "unit_cost_paisa": None,
}


def _extraction(document: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(document["extraction_json"] or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _load(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    document = repo.document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="That entry does not exist.")
    return document


@router.get("/review", response_class=HTMLResponse)
def review_queue(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    documents = repo.documents_by_status(conn, "pending_review", limit=200)
    for document in documents:
        notes = _extraction(document).get("notes") or []
        document["first_note"] = notes[0] if notes else None

    return templates.TemplateResponse(
        request,
        "review.html", context(request, conn, "review", documents=documents)
    )


@router.get("/review/{document_id}", response_class=HTMLResponse)
def review_detail(
    document_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    document = _load(conn, document_id)
    extraction = _extraction(document)
    fields = extraction.get("fields") or {}

    stock_lines = list(fields.get("lines") or [])
    if not stock_lines:
        stock_lines = [dict(BLANK_STOCK_LINE)]

    stored = document.get("stored_path")
    has_image = bool(stored) and Path(stored).suffix.lower() in IMAGE_SUFFIXES

    return templates.TemplateResponse(
        request,
        "review_detail.html",
        context(
            request, conn, "review",
            doc=document,
            fields=fields,
            notes=extraction.get("notes") or [],
            stock_lines=stock_lines,
            has_image=has_image,
            today=iso(local_today(settings.timezone)),
            type_options=TYPE_OPTIONS,
            payment_methods=PAYMENT_METHODS,
            categories=CATEGORIES,
        ),
    )


@router.get("/review/{document_id}/file")
def review_file(
    document_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    document = _load(conn, document_id)
    stored = document.get("stored_path")
    if not stored:
        raise HTTPException(status_code=404, detail="This entry has no file.")

    path = Path(stored).resolve()
    uploads = settings.uploads_dir.resolve()
    # Serve only from the uploads folder, whatever the database happens to hold.
    if not path.is_file() or uploads not in path.parents:
        raise HTTPException(status_code=404, detail="The file is no longer available.")
    return FileResponse(path)


@router.post("/review/{document_id}/accept")
async def accept_entry(
    document_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    form = await request.form()
    doc_type = str(form.get("doc_type") or "").strip()

    try:
        fields = fields_for(doc_type, form)
        posting.accept(conn, document_id, doc_type=doc_type, fields=fields,
                       note=str(form.get("notes") or "") or None)
    except (ValidationError, ConflictError) as exc:
        return redirect(f"/review/{document_id}", str(exc), "error")
    except NotFoundError as exc:
        return redirect("/review", str(exc), "error")

    return redirect("/review", f"Entry {document_id} recorded.", "ok")


@router.post("/review/{document_id}/reject")
def reject_entry(
    document_id: int,
    notes: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        posting.reject(conn, document_id, note=notes or None)
    except NotFoundError as exc:
        return redirect("/review", str(exc), "error")
    return redirect("/review", f"Entry {document_id} discarded. Nothing was recorded.", "warn")
