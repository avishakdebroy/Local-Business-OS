"""The pages a paired phone sees.

Deliberately a separate, tiny surface. A phone on the shop Wi-Fi can photograph
a barcode or a handwritten note and read today's figures — it cannot edit the
books, void an entry, or reach the backup and settings screens. Those stay on
the laptop, where physical access is the control.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from lbos.api.deps import get_conn, get_settings
from lbos.api.templating import redirect, templates
from lbos.capture import barcode, storage, text_extract
from lbos.domain.errors import ValidationError
from lbos.domain.periods import iso, local_today
from lbos.ledger import posting
from lbos.ledger import repositories as repo
from lbos.phone import pairing
from lbos.settings import Settings

router = APIRouter(prefix="/phone", tags=["phone"])


def current_device(request: Request, conn: sqlite3.Connection) -> dict[str, Any] | None:
    return pairing.device_for(conn, request.cookies.get(pairing.COOKIE_NAME))


def _needs_pairing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "phone_pair_needed.html", {"request": request}, status_code=401
    )


@router.get("/pair", response_class=HTMLResponse)
def pair(
    request: Request,
    code: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Opened by scanning the QR code shown on the computer."""
    if not code:
        return _needs_pairing(request)
    try:
        token = pairing.redeem(conn, code, device_name="Phone")
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "phone_pair_needed.html", {"request": request, "error": str(exc)},
            status_code=400,
        )

    response = RedirectResponse("/phone", status_code=303)
    response.set_cookie(
        pairing.COOKIE_NAME, token,
        max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", path="/",
    )
    return response


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    device = current_device(request, conn)
    if not device:
        return _needs_pairing(request)

    today = iso(local_today(settings.timezone))
    return templates.TemplateResponse(
        request, "phone_home.html",
        {
            "request": request,
            "device": device,
            "today": today,
            "totals": repo.money_totals(conn, today, today),
            "credit": repo.credit_totals(conn),
            "pending": repo.document_status_counts(conn).get("pending_review", 0),
            "msg": request.query_params.get("msg"),
            "kind": request.query_params.get("kind", "ok"),
        },
    )


@router.get("/scan", response_class=HTMLResponse)
def scan_form(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    if not current_device(request, conn):
        return _needs_pairing(request)
    return templates.TemplateResponse(
        request, "phone_scan.html", {"request": request, "result": None}
    )


@router.post("/scan", response_class=HTMLResponse)
def scan_submit(
    request: Request,
    photo: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Read a product barcode out of a photo taken on the phone."""
    if not current_device(request, conn):
        return _needs_pairing(request)

    found = barcode.first_product_code(photo.file.read())
    item = None
    if found:
        row = conn.execute(
            "SELECT i.*, s.on_hand_milli FROM items i"
            " LEFT JOIN item_stock s ON s.item_id = i.id WHERE i.barcode = ?",
            (found.text,),
        ).fetchone()
        item = dict(row) if row else None

    return templates.TemplateResponse(
        request, "phone_scan.html",
        {"request": request, "result": {"code": found, "item": item}},
    )


@router.post("/scan/save")
def scan_save(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    brand: str = Form(""),
    variant: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Register a product the shop has not seen before, straight from the phone."""
    if not current_device(request, conn):
        return _needs_pairing(request)
    if not name.strip():
        return redirect("/phone/scan", "The product needs a name.", "error")

    item_id = repo.upsert_item(conn, name=name)
    conn.execute(
        "UPDATE items SET barcode = ?, brand = ?, variant = ? WHERE id = ?",
        (code.strip() or None, brand.strip() or None, variant.strip() or None, item_id),
    )
    conn.commit()
    return redirect("/phone", f"“{name.strip()}” saved against that barcode.", "ok")


@router.get("/note", response_class=HTMLResponse)
def note_form(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    if not current_device(request, conn):
        return _needs_pairing(request)
    return templates.TemplateResponse(request, "phone_note.html", {"request": request})


@router.post("/note")
def note_submit(
    request: Request,
    photo: UploadFile = File(...),
    hint: str = Form("auto"),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    """Photograph a handwritten page or a supplier bill into the review queue."""
    if not current_device(request, conn):
        return _needs_pairing(request)

    try:
        stored = storage.save_upload(settings, photo.filename, photo.file.read())
    except ValidationError as exc:
        return redirect("/phone/note", str(exc), "error")

    extracted = text_extract.extract(stored.path, settings)
    result = posting.capture(
        conn, settings, text=extracted.text, hint=hint,
        source_kind="file", stored=stored, warnings=extracted.warnings,
    )

    if result.is_duplicate:
        return redirect("/phone", "That page was already sent in.", "warn")
    return redirect(
        "/phone",
        "Photo saved. Check it on the computer before it counts."
        if result.needs_review else "Photo saved and recorded.",
        "ok" if not result.needs_review else "warn",
    )
