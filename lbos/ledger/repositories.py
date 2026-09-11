"""Every SQL statement in the application.

Keeping queries in one module means a schema change has exactly one place to
touch, and it keeps SQL out of the request handlers where it is impossible to
test in isolation.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from lbos.domain.periods import now_utc_iso

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def name_key(name: str) -> str:
    """Collapse an item name so 'Miniket  Rice' and 'miniket rice' are one item."""
    return _NON_WORD.sub(" ", (name or "").casefold()).strip()


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row else None


# --- Documents --------------------------------------------------------------


def insert_document(
    conn: sqlite3.Connection,
    *,
    content_hash: str,
    source_kind: str,
    doc_type: str,
    status: str,
    confidence: float,
    raw_text: str,
    extraction: dict[str, Any],
    extractor: str,
    original_filename: str | None = None,
    stored_path: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO documents (
            content_hash, source_kind, original_filename, stored_path, raw_text,
            doc_type, status, confidence, extractor, extraction_json, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_hash, source_kind, original_filename, stored_path, raw_text,
            doc_type, status, float(confidence), extractor,
            json.dumps(extraction, ensure_ascii=False), now_utc_iso(),
        ),
    )
    return int(cursor.lastrowid)


def document_by_hash(conn: sqlite3.Connection, content_hash: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM documents WHERE content_hash = ?", (content_hash,)))


def document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)))


def update_document_status(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    status: str,
    doc_type: str | None = None,
    note: str | None = None,
    extraction: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> None:
    sets = ["status = ?", "reviewed_at = ?"]
    params: list[Any] = [status, now_utc_iso()]
    if doc_type is not None:
        sets.append("doc_type = ?")
        params.append(doc_type)
    if note is not None:
        sets.append("review_note = ?")
        params.append(note)
    if extraction is not None:
        sets.append("extraction_json = ?")
        params.append(json.dumps(extraction, ensure_ascii=False))
    if confidence is not None:
        sets.append("confidence = ?")
        params.append(float(confidence))
    params.append(document_id)
    conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", params)


def documents_by_status(
    conn: sqlite3.Connection, status: str, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM documents WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    )


def recent_documents(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM documents ORDER BY id DESC LIMIT ?", (limit,)))


def document_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {"pending_review": 0, "posted": 0, "rejected": 0}
    for row in conn.execute("SELECT status, COUNT(*) AS c FROM documents GROUP BY status"):
        counts[row["status"]] = int(row["c"])
    return counts


# --- Money entries ----------------------------------------------------------


def insert_money_entry(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    entry_date: str,
    direction: str,
    total_paisa: int,
    tax_paisa: int = 0,
    currency: str = "BDT",
    party: str | None = None,
    category: str | None = None,
    payment_method: str | None = None,
    notes: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO money_entries (
            document_id, entry_date, direction, party, total_paisa, tax_paisa,
            currency, category, payment_method, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id, entry_date, direction, party, int(total_paisa), int(tax_paisa),
            currency, category, payment_method, notes, now_utc_iso(),
        ),
    )
    return int(cursor.lastrowid)


def void_money_entries_for_document(
    conn: sqlite3.Connection, document_id: int, reason: str
) -> int:
    cursor = conn.execute(
        """
        UPDATE money_entries SET voided_at = ?, void_reason = ?
        WHERE document_id = ? AND voided_at IS NULL
        """,
        (now_utc_iso(), reason, document_id),
    )
    return cursor.rowcount


def void_money_entry(conn: sqlite3.Connection, entry_id: int, reason: str) -> int:
    cursor = conn.execute(
        "UPDATE money_entries SET voided_at = ?, void_reason = ? WHERE id = ? AND voided_at IS NULL",
        (now_utc_iso(), reason, entry_id),
    )
    return cursor.rowcount


def money_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM money_entries WHERE id = ?", (entry_id,)))


def money_entries(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    direction: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Live entries whose *business date* falls in [start, end], inclusive."""
    sql = [
        """
        SELECT m.*, d.original_filename, d.stored_path
        FROM money_entries m
        JOIN documents d ON d.id = m.document_id
        WHERE m.voided_at IS NULL AND m.entry_date BETWEEN ? AND ?
        """
    ]
    params: list[Any] = [start, end]
    if direction:
        sql.append("AND m.direction = ?")
        params.append(direction)
    sql.append("ORDER BY m.entry_date DESC, m.id DESC LIMIT ?")
    params.append(limit)
    return _rows(conn.execute(" ".join(sql), params))


def money_totals(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """Sales, purchases and counts for a business-date range, in paisa."""
    result = {
        "sale_paisa": 0, "sale_count": 0, "sale_tax_paisa": 0,
        "purchase_paisa": 0, "purchase_count": 0, "purchase_tax_paisa": 0,
    }
    for row in conn.execute(
        """
        SELECT direction,
               COALESCE(SUM(total_paisa), 0) AS total,
               COALESCE(SUM(tax_paisa), 0)   AS tax,
               COUNT(*)                      AS n
        FROM money_entries
        WHERE voided_at IS NULL AND entry_date BETWEEN ? AND ?
        GROUP BY direction
        """,
        (start, end),
    ):
        result[f"{row['direction']}_paisa"] = int(row["total"])
        result[f"{row['direction']}_tax_paisa"] = int(row["tax"])
        result[f"{row['direction']}_count"] = int(row["n"])
    result["net_paisa"] = result["sale_paisa"] - result["purchase_paisa"]
    return result


def category_breakdown(
    conn: sqlite3.Connection, start: str, end: str, direction: str, limit: int = 10
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT COALESCE(NULLIF(category, ''), 'uncategorised') AS category,
                   SUM(total_paisa) AS total_paisa,
                   COUNT(*)         AS n
            FROM money_entries
            WHERE voided_at IS NULL AND direction = ? AND entry_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY total_paisa DESC LIMIT ?
            """,
            (direction, start, end, limit),
        )
    )


def payment_breakdown(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT COALESCE(NULLIF(payment_method, ''), 'unknown') AS method,
                   SUM(total_paisa) AS total_paisa,
                   COUNT(*)         AS n
            FROM money_entries
            WHERE voided_at IS NULL AND direction = 'sale' AND entry_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY total_paisa DESC
            """,
            (start, end),
        )
    )


# --- Items and stock --------------------------------------------------------


def upsert_item(
    conn: sqlite3.Connection,
    *,
    name: str,
    unit: str = "pcs",
    sku: str | None = None,
    reorder_level_milli: int | None = None,
) -> int:
    """Find an item by normalised name, creating it if this is the first sighting."""
    key = name_key(name)
    now = now_utc_iso()
    existing = _row(conn.execute("SELECT * FROM items WHERE name_key = ?", (key,)))

    if existing:
        updates = ["updated_at = ?"]
        params: list[Any] = [now]
        if sku and not existing["sku"]:
            updates.append("sku = ?")
            params.append(sku)
        if reorder_level_milli is not None:
            updates.append("reorder_level_milli = ?")
            params.append(int(reorder_level_milli))
        params.append(existing["id"])
        conn.execute(f"UPDATE items SET {', '.join(updates)} WHERE id = ?", params)
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO items (sku, name, name_key, unit, reorder_level_milli, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (sku or None, name.strip()[:120], key, unit, int(reorder_level_milli or 0), now, now),
    )
    return int(cursor.lastrowid)


def set_reorder_level(conn: sqlite3.Connection, item_id: int, reorder_level_milli: int) -> None:
    conn.execute(
        "UPDATE items SET reorder_level_milli = ?, updated_at = ? WHERE id = ?",
        (int(reorder_level_milli), now_utc_iso(), item_id),
    )


def insert_stock_move(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    document_id: int | None,
    entry_date: str,
    direction: str,
    qty_milli: int,
    unit_cost_paisa: int | None = None,
    notes: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO stock_moves (
            item_id, document_id, entry_date, direction, qty_milli,
            unit_cost_paisa, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id, document_id, entry_date, direction, int(qty_milli),
            None if unit_cost_paisa is None else int(unit_cost_paisa),
            notes, now_utc_iso(),
        ),
    )
    return int(cursor.lastrowid)


def void_stock_moves_for_document(conn: sqlite3.Connection, document_id: int, reason: str) -> int:
    cursor = conn.execute(
        """
        UPDATE stock_moves SET voided_at = ?, void_reason = ?
        WHERE document_id = ? AND voided_at IS NULL
        """,
        (now_utc_iso(), reason, document_id),
    )
    return cursor.rowcount


def stock_levels(conn: sqlite3.Connection, low_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM item_stock"
    if low_only:
        sql += " WHERE on_hand_milli <= reorder_level_milli"
    sql += " ORDER BY (on_hand_milli - reorder_level_milli) ASC, name ASC"
    return _rows(conn.execute(sql))


def stock_moves(
    conn: sqlite3.Connection, item_id: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    sql = [
        """
        SELECT s.*, i.name AS item_name, i.unit AS item_unit
        FROM stock_moves s JOIN items i ON i.id = s.item_id
        WHERE s.voided_at IS NULL
        """
    ]
    params: list[Any] = []
    if item_id is not None:
        sql.append("AND s.item_id = ?")
        params.append(item_id)
    sql.append("ORDER BY s.entry_date DESC, s.id DESC LIMIT ?")
    params.append(limit)
    return _rows(conn.execute(" ".join(sql), params))


# --- Memos ------------------------------------------------------------------


def upsert_memo(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    entry_date: str,
    title: str,
    body: str,
    tags: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO memos (document_id, entry_date, title, body, tags, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            entry_date = excluded.entry_date,
            title      = excluded.title,
            body       = excluded.body,
            tags       = excluded.tags
        """,
        (document_id, entry_date, title[:200], body, tags, now_utc_iso()),
    )


def delete_memo_for_document(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM memos WHERE document_id = ?", (document_id,))


def memos(conn: sqlite3.Connection, start: str, end: str, limit: int = 200) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT * FROM memos WHERE entry_date BETWEEN ? AND ?
            ORDER BY entry_date DESC, id DESC LIMIT ?
            """,
            (start, end, limit),
        )
    )


# --- Reports and jobs -------------------------------------------------------


def insert_report_run(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    report_path: str | None,
    summary: dict[str, Any],
    delivery_status: str,
    delivery_detail: str | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO report_runs (
            period_start, period_end, report_path, summary_json,
            delivery_status, delivery_detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            period_start, period_end, report_path,
            json.dumps(summary, ensure_ascii=False),
            delivery_status, delivery_detail, now_utc_iso(),
        ),
    )
    return int(cursor.lastrowid)


def latest_report_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM report_runs ORDER BY id DESC LIMIT 1"))


def report_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM report_runs ORDER BY id DESC LIMIT ?", (limit,)))


def insert_job_run(
    conn: sqlite3.Connection, *, job_name: str, status: str, detail: str | None,
    started_at: str, finished_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO job_runs (job_name, status, detail, started_at, finished_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_name, status, detail, started_at, finished_at),
    )
    return int(cursor.lastrowid)


def recent_job_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT ?", (limit,)))


def failing_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The latest run of each job, where that latest run failed."""
    return _rows(
        conn.execute(
            """
            SELECT j.* FROM job_runs j
            JOIN (SELECT job_name, MAX(id) AS id FROM job_runs GROUP BY job_name) last
              ON last.id = j.id
            WHERE j.status = 'error'
            """
        )
    )


def update_report_delivery(
    conn: sqlite3.Connection, report_id: int, status: str, detail: str | None
) -> None:
    conn.execute(
        "UPDATE report_runs SET delivery_status = ?, delivery_detail = ? WHERE id = ?",
        (status, detail, report_id),
    )


# --- Customers and credit (বাকি খাতা) ---------------------------------------
#
# A positive balance means the customer owes the shop. Balances are derived from
# entries by the customer_balance view and are never stored, for the same reason
# stock levels are not: a stored total can drift away from its own history.


def upsert_customer(
    conn: sqlite3.Connection,
    *,
    name: str,
    phone: str | None = None,
    note: str | None = None,
) -> int:
    key = name_key(name)
    if not key:
        raise ValueError("a customer needs a name")
    now = now_utc_iso()
    existing = _row(conn.execute("SELECT id FROM customers WHERE name_key = ?", (key,)))
    if existing:
        sets, params = ["updated_at = ?"], [now]
        if phone:
            sets.append("phone = ?")
            params.append(phone)
        if note:
            sets.append("note = ?")
            params.append(note)
        params.append(existing["id"])
        conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE id = ?", params)
        return int(existing["id"])

    cursor = conn.execute(
        "INSERT INTO customers (name, name_key, phone, note, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (name.strip()[:120], key, phone, note, now, now),
    )
    return int(cursor.lastrowid)


def customer(conn: sqlite3.Connection, customer_id: int) -> dict[str, Any] | None:
    return _row(
        conn.execute("SELECT * FROM customer_balance WHERE customer_id = ?", (customer_id,))
    )


def customers_with_balance(
    conn: sqlite3.Connection, only_owing: bool = False, search: str | None = None
) -> list[dict[str, Any]]:
    sql = ["SELECT * FROM customer_balance WHERE 1 = 1"]
    params: list[Any] = []
    if only_owing:
        sql.append("AND balance_paisa > 0")
    if search:
        sql.append("AND (name LIKE ? OR IFNULL(phone, '') LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    sql.append("ORDER BY balance_paisa DESC, name ASC")
    return _rows(conn.execute(" ".join(sql), params))


def insert_credit_entry(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    entry_date: str,
    kind: str,
    amount_paisa: int,
    note: str | None = None,
    document_id: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO credit_entries
            (customer_id, document_id, entry_date, kind, amount_paisa, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (customer_id, document_id, entry_date, kind, int(amount_paisa), note, now_utc_iso()),
    )
    return int(cursor.lastrowid)


def credit_entries(
    conn: sqlite3.Connection, customer_id: int, limit: int = 200
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT * FROM credit_entries
            WHERE customer_id = ? AND voided_at IS NULL
            ORDER BY entry_date DESC, id DESC LIMIT ?
            """,
            (customer_id, limit),
        )
    )


def credit_entries_between(
    conn: sqlite3.Connection, start: str, end: str, limit: int = 500
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT e.*, c.name AS customer_name
            FROM credit_entries e JOIN customers c ON c.id = e.customer_id
            WHERE e.voided_at IS NULL AND e.entry_date BETWEEN ? AND ?
            ORDER BY e.entry_date DESC, e.id DESC LIMIT ?
            """,
            (start, end, limit),
        )
    )


def void_credit_entry(conn: sqlite3.Connection, entry_id: int, reason: str) -> int:
    cursor = conn.execute(
        "UPDATE credit_entries SET voided_at = ?, void_reason = ?"
        " WHERE id = ? AND voided_at IS NULL",
        (now_utc_iso(), reason, entry_id),
    )
    return cursor.rowcount


def credit_totals(conn: sqlite3.Connection) -> dict[str, int]:
    row = _row(
        conn.execute(
            """
            SELECT COALESCE(SUM(balance_paisa), 0) AS owed,
                   COUNT(*)                        AS customers
            FROM customer_balance WHERE balance_paisa > 0
            """
        )
    ) or {"owed": 0, "customers": 0}
    return {"outstanding_paisa": int(row["owed"]), "customers_owing": int(row["customers"])}


def credit_movement(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """New credit given and repayments received in a date range."""
    result = {"charge_paisa": 0, "payment_paisa": 0}
    for row in conn.execute(
        """
        SELECT kind, COALESCE(SUM(amount_paisa), 0) AS total
        FROM credit_entries
        WHERE voided_at IS NULL AND entry_date BETWEEN ? AND ?
        GROUP BY kind
        """,
        (start, end),
    ):
        result[f"{row['kind']}_paisa"] = int(row["total"])
    return result
