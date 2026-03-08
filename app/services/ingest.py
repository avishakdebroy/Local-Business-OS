from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from app.db import get_conn
from app.services.llm import parse_document_with_llm


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _insert_receipt(conn, document_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO receipts (document_id, receipt_date, vendor, total_amount, tax_amount, category, payment_method, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            data.get("date"),
            data.get("vendor"),
            float(data.get("total_amount") or 0),
            float(data.get("tax_amount") or 0),
            data.get("category"),
            data.get("payment_method"),
            data.get("notes"),
            _now_iso(),
        ),
    )


def _ensure_item(conn, data: dict[str, Any]) -> int:
    sku = data.get("sku") or None
    name = data.get("name") or "Unknown Item"
    unit = data.get("unit") or "pcs"
    reorder = float(data.get("reorder_level") or 0)

    if sku:
        conn.execute(
            """
            INSERT INTO inventory_items (sku, name, unit, current_qty, reorder_level, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                name = excluded.name,
                unit = excluded.unit,
                reorder_level = excluded.reorder_level,
                updated_at = excluded.updated_at
            """,
            (sku, name, unit, reorder, _now_iso()),
        )
        row = conn.execute("SELECT id FROM inventory_items WHERE sku = ?", (sku,)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM inventory_items WHERE name = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            cur = conn.execute(
                """
                INSERT INTO inventory_items (sku, name, unit, current_qty, reorder_level, updated_at)
                VALUES (NULL, ?, ?, 0, ?, ?)
                """,
                (name, unit, reorder, _now_iso()),
            )
            return int(cur.lastrowid)

    return int(row["id"])


def _insert_inventory_move(conn, document_id: int, data: dict[str, Any]) -> None:
    item_id = _ensure_item(conn, data)
    move_type = (data.get("move_type") or "in").lower()
    qty = float(data.get("qty") or 0)
    qty_effect = qty if move_type == "in" else -qty

    conn.execute(
        """
        INSERT INTO inventory_moves (item_id, document_id, move_type, qty, unit_cost, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            document_id,
            move_type,
            qty,
            float(data.get("unit_cost") or 0),
            data.get("notes"),
            _now_iso(),
        ),
    )

    conn.execute(
        """
        UPDATE inventory_items
        SET current_qty = current_qty + ?, updated_at = ?
        WHERE id = ?
        """,
        (qty_effect, _now_iso(), item_id),
    )


def _insert_memo(conn, document_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO memos (document_id, title, body, tags, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            document_id,
            data.get("title") or "Memo",
            data.get("body") or "",
            data.get("tags") or "",
            _now_iso(),
        ),
    )


def ingest_text(text: str, requested_type: str = "auto", file_path: str | None = None) -> dict[str, Any]:
    parsed = parse_document_with_llm(text=text, requested_type=requested_type)
    inferred_type = parsed.get("document_type", "memo")
    confidence = float(parsed.get("confidence") or 0)

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (source_type, file_path, raw_text, parsed_json, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                requested_type,
                file_path,
                text,
                json.dumps(parsed, ensure_ascii=False),
                confidence,
                _now_iso(),
            ),
        )
        document_id = int(cur.lastrowid)

        if inferred_type == "receipt" and isinstance(parsed.get("receipt"), dict):
            _insert_receipt(conn, document_id, parsed["receipt"])
        elif inferred_type == "inventory" and isinstance(parsed.get("inventory"), dict):
            _insert_inventory_move(conn, document_id, parsed["inventory"])
        else:
            memo_payload = parsed.get("memo") if isinstance(parsed.get("memo"), dict) else {
                "title": "Memo",
                "body": text,
                "tags": "",
            }
            _insert_memo(conn, document_id, memo_payload)

        conn.commit()

    return {
        "document_id": document_id,
        "inferred_type": inferred_type,
        "confidence": confidence,
    }
