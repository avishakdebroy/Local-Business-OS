"""Deciding what reaches the books, and writing it when it does.

The rule this module exists to enforce: an automatic reading is a *proposal*.
It becomes a ledger row only when it is complete, internally valid, and either
confident enough or accepted by the operator. Everything else waits on the
review screen, where it stays visible instead of quietly becoming a wrong total.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from lbos.capture.storage import StoredFile, hash_text
from lbos.db.connection import transaction
from lbos.domain.entities import CaptureResult, Extraction
from lbos.domain.errors import ConflictError, NotFoundError, ValidationError
from lbos.domain.money import format_paisa
from lbos.domain.periods import iso, parse_iso_date
from lbos.domain.quantity import canonical_unit
from lbos.interpretation.pipeline import decide_status, interpret
from lbos.ledger import repositories as repo
from lbos.settings import Settings

MAX_PAISA = 10**13  # ৳100 crore, far beyond any real single entry
MAX_QTY_MILLI = 10**12


# --- Validation -------------------------------------------------------------


def _require_date(value: Any, label: str = "Date") -> str:
    parsed = parse_iso_date(str(value or ""))
    if parsed is None:
        raise ValidationError(f"{label} must be a real date in YYYY-MM-DD form.")
    return iso(parsed)


def _require_paisa(value: Any, label: str, *, allow_zero: bool = False) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be an amount of money.") from None
    if amount < 0:
        raise ValidationError(f"{label} cannot be negative.")
    if amount == 0 and not allow_zero:
        raise ValidationError(f"{label} must be more than zero.")
    if amount >= MAX_PAISA:
        raise ValidationError(f"{label} looks far too large ({format_paisa(amount)}).")
    return amount


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def validate_money(fields: dict[str, Any], doc_type: str) -> dict[str, Any]:
    total = _require_paisa(fields.get("total_paisa"), "Amount")
    tax = _require_paisa(fields.get("tax_paisa") or 0, "VAT", allow_zero=True)
    if tax > total:
        raise ValidationError(
            f"VAT ({format_paisa(tax)}) cannot be more than the total ({format_paisa(total)})."
        )
    return {
        "entry_date": _require_date(fields.get("entry_date")),
        "direction": doc_type,
        "party": _clean_text(fields.get("party"), 120),
        "total_paisa": total,
        "tax_paisa": tax,
        "category": _clean_text(fields.get("category"), 40),
        "payment_method": _clean_text(fields.get("payment_method"), 20),
        "notes": _clean_text(fields.get("notes"), 2000),
    }


def validate_stock(fields: dict[str, Any]) -> dict[str, Any]:
    entry_date = _require_date(fields.get("entry_date"))
    raw_lines = fields.get("lines") or []
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValidationError("Add at least one item line.")

    lines: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise ValidationError(f"Line {index} is not filled in correctly.")
        name = _clean_text(raw.get("name"), 120)
        if not name:
            raise ValidationError(f"Line {index}: the item needs a name.")
        try:
            qty = int(raw.get("qty_milli"))
        except (TypeError, ValueError):
            raise ValidationError(f"Line {index}: the quantity is not a number.") from None
        if qty <= 0:
            raise ValidationError(f"Line {index}: the quantity must be more than zero.")
        if qty >= MAX_QTY_MILLI:
            raise ValidationError(f"Line {index}: that quantity looks far too large.")
        direction = str(raw.get("direction") or "").strip().lower()
        if direction not in ("in", "out"):
            raise ValidationError(f"Line {index}: say whether the stock came in or went out.")
        cost = raw.get("unit_cost_paisa")
        lines.append(
            {
                "name": name,
                "qty_milli": qty,
                "unit": canonical_unit(raw.get("unit")),
                "direction": direction,
                "unit_cost_paisa": None if cost in (None, "") else _require_paisa(
                    cost, f"Line {index} unit cost", allow_zero=True
                ),
            }
        )
    return {"entry_date": entry_date, "lines": lines, "notes": _clean_text(fields.get("notes"), 2000)}


def validate_memo(fields: dict[str, Any]) -> dict[str, Any]:
    body = str(fields.get("body") or "").strip()
    if not body:
        raise ValidationError("A note cannot be empty.")
    return {
        "entry_date": _require_date(fields.get("entry_date")),
        "title": _clean_text(fields.get("title"), 80) or body.splitlines()[0][:80],
        "body": body[:20000],
        "tags": _clean_text(fields.get("tags"), 200) or "",
    }


def validate(doc_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    if doc_type in ("sale", "purchase"):
        return validate_money(fields, doc_type)
    if doc_type == "stock":
        return validate_stock(fields)
    if doc_type == "memo":
        return validate_memo(fields)
    raise ValidationError(f"Unknown entry type: {doc_type}")


# --- Writing to the books ---------------------------------------------------


def _supersede(conn: sqlite3.Connection, document_id: int, reason: str) -> None:
    """Retire any live ledger rows this document previously produced."""
    repo.void_money_entries_for_document(conn, document_id, reason)
    repo.void_stock_moves_for_document(conn, document_id, reason)
    repo.delete_memo_for_document(conn, document_id)


def write_ledger(
    conn: sqlite3.Connection, document_id: int, doc_type: str, clean: dict[str, Any]
) -> None:
    """Write validated fields as ledger rows, superseding any earlier version."""
    _supersede(conn, document_id, "superseded by correction")

    if doc_type in ("sale", "purchase"):
        repo.insert_money_entry(conn, document_id=document_id, **clean)
        return

    if doc_type == "stock":
        for line in clean["lines"]:
            item_id = repo.upsert_item(conn, name=line["name"], unit=line["unit"])
            repo.insert_stock_move(
                conn,
                item_id=item_id,
                document_id=document_id,
                entry_date=clean["entry_date"],
                direction=line["direction"],
                qty_milli=line["qty_milli"],
                unit_cost_paisa=line["unit_cost_paisa"],
                notes=clean.get("notes"),
            )
        return

    repo.upsert_memo(conn, document_id=document_id, **clean)


# --- Capture ----------------------------------------------------------------


def capture(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    text: str,
    hint: str = "auto",
    source_kind: str = "text",
    stored: StoredFile | None = None,
    warnings: list[str] | None = None,
    today: date | None = None,
) -> CaptureResult:
    """Take one document in. Always succeeds in storing it; may hold it for review."""
    # Files are identified by their bytes, not their extracted text: two
    # different photos that both OCR to nothing are still two documents.
    content_hash = stored.sha256 if stored else hash_text(text)

    existing = repo.document_by_hash(conn, content_hash)
    if existing:
        return CaptureResult(
            document_id=int(existing["id"]),
            doc_type=existing["doc_type"],
            status=existing["status"],
            confidence=float(existing["confidence"]),
            duplicate_of=int(existing["id"]),
            message="This document was already recorded, so nothing was added again.",
        )

    extraction = interpret(text, settings, hint=hint, today=today)
    for warning in warnings or []:
        extraction.notes.append(warning)

    status = decide_status(extraction, settings)
    if not (text or "").strip():
        status = "pending_review"
        extraction.confidence = min(extraction.confidence, 0.1)
        extraction.notes.append("No text could be read, so the details must be typed in.")

    clean: dict[str, Any] | None = None
    if status == "posted":
        try:
            clean = validate(extraction.doc_type, extraction.fields)
        except ValidationError as exc:
            status = "pending_review"
            extraction.notes.append(str(exc))

    with transaction(conn):
        document_id = repo.insert_document(
            conn,
            content_hash=content_hash,
            source_kind=source_kind,
            doc_type=extraction.doc_type,
            status=status,
            confidence=extraction.confidence,
            raw_text=text or "",
            extraction=extraction.to_json_dict(),
            extractor=extraction.extractor,
            original_filename=stored.original_filename if stored else None,
            stored_path=str(stored.path) if stored else None,
        )
        if status == "posted" and clean is not None:
            write_ledger(conn, document_id, extraction.doc_type, clean)

    return CaptureResult(
        document_id=document_id,
        doc_type=extraction.doc_type,
        status=status,
        confidence=extraction.confidence,
        message=(
            "Recorded."
            if status == "posted"
            else "Saved and waiting for you on the Review screen."
        ),
    )


# --- Review actions ---------------------------------------------------------


def _load(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    row = repo.document(conn, document_id)
    if row is None:
        raise NotFoundError(f"Entry {document_id} does not exist.")
    return row


def accept(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    doc_type: str,
    fields: dict[str, Any],
    note: str | None = None,
) -> None:
    """Post an entry with the operator's corrections. Raises on invalid input."""
    row = _load(conn, document_id)
    if row["status"] == "rejected":
        raise ConflictError("This entry was discarded. Restore it before accepting.")

    clean = validate(doc_type, fields)
    extraction = Extraction(
        doc_type=doc_type,
        confidence=1.0,
        fields=clean,
        extractor="manual",
        notes=["Checked and accepted by the operator."],
    )

    with transaction(conn):
        write_ledger(conn, document_id, doc_type, clean)
        repo.update_document_status(
            conn,
            document_id,
            status="posted",
            doc_type=doc_type,
            note=note,
            extraction=extraction.to_json_dict(),
            confidence=1.0,
        )


def reject(conn: sqlite3.Connection, document_id: int, note: str | None = None) -> None:
    """Discard an entry without deleting the document it came from."""
    _load(conn, document_id)
    with transaction(conn):
        _supersede(conn, document_id, "entry discarded")
        repo.update_document_status(
            conn, document_id, status="rejected", note=note or "Discarded by the operator."
        )


def unpost(conn: sqlite3.Connection, document_id: int, reason: str) -> None:
    """Take a posted entry back out of the books and return it to review."""
    row = _load(conn, document_id)
    if row["status"] != "posted":
        raise ConflictError("Only a recorded entry can be undone.")
    with transaction(conn):
        _supersede(conn, document_id, reason)
        repo.update_document_status(conn, document_id, status="pending_review", note=reason)
