"""The day book — আজকের পাতা.

One page per day, the way the paper ledger reads: everything that happened,
in order, with the day's cash position at the bottom. This is the screen a
shopkeeper recognises without being taught, which is why it is the landing
page rather than a dashboard of tiles.

Credit is kept visibly separate from cash. Goods given on বাকি are revenue but
*not* money in the drawer, and a day book that blurs the two teaches the owner
to over-count the day's takings.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from lbos.domain.periods import iso
from lbos.ledger import repositories as repo


def _line(kind: str, label: str, amount_paisa: int, detail: str = "", ref: str = "") -> dict[str, Any]:
    return {"kind": kind, "label": label, "amount_paisa": amount_paisa, "detail": detail, "ref": ref}


def build(conn: sqlite3.Connection, day: date) -> dict[str, Any]:
    """Everything that happened on one business day."""
    today = iso(day)
    money = repo.money_entries(conn, today, today)
    credit = repo.credit_entries_between(conn, today, today)
    stock = [m for m in repo.stock_moves(conn, limit=500) if m["entry_date"] == today]
    notes = repo.memos(conn, today, today, limit=50)

    lines: list[dict[str, Any]] = []
    cash_in = cash_out = 0

    for entry in money:
        if entry["direction"] == "sale":
            # A sale booked to 'due' is revenue, but no money entered the drawer.
            on_credit = (entry["payment_method"] or "") == "due"
            if not on_credit:
                cash_in += entry["total_paisa"]
            lines.append(_line(
                "sale", entry["party"] or "Sale / বিক্রয়", entry["total_paisa"],
                detail=("on credit / বাকি" if on_credit else (entry["payment_method"] or "cash")),
                ref=f"/ledger?start={today}&end={today}",
            ))
        else:
            cash_out += entry["total_paisa"]
            lines.append(_line(
                "purchase", entry["party"] or "Purchase / ক্রয়", entry["total_paisa"],
                detail=entry["category"] or "", ref=f"/ledger?start={today}&end={today}",
            ))

    for entry in credit:
        if entry["kind"] == "payment":
            cash_in += entry["amount_paisa"]
            lines.append(_line(
                "credit_payment", f"{entry['customer_name']} paid / জমা",
                entry["amount_paisa"], detail=entry["note"] or "",
                ref=f"/khata/{entry['customer_id']}",
            ))
        else:
            lines.append(_line(
                "credit_charge", f"{entry['customer_name']} on credit / বাকি",
                entry["amount_paisa"], detail=entry["note"] or "",
                ref=f"/khata/{entry['customer_id']}",
            ))

    for move in stock:
        lines.append(_line(
            "stock",
            f"{move['item_name']} {'in' if move['direction'] == 'in' else 'out'}",
            0,
            detail=f"{move['qty_milli'] / 1000:g} {move['item_unit']}"
                   + (f" · {move['reason']}" if move.get("reason") not in (None, "", "adjust") else ""),
            ref="/stock",
        ))

    for memo in notes:
        lines.append(_line("note", memo["title"], 0, detail=memo["body"][:80], ref="/ledger"))

    movement = repo.credit_movement(conn, today, today)
    outstanding = repo.credit_totals(conn)

    return {
        "day": today,
        "previous_day": iso(day - timedelta(days=1)),
        "next_day": iso(day + timedelta(days=1)),
        "lines": lines,
        "cash_in_paisa": cash_in,
        "cash_out_paisa": cash_out,
        "net_cash_paisa": cash_in - cash_out,
        "credit_given_paisa": movement["charge_paisa"],
        "credit_received_paisa": movement["payment_paisa"],
        "outstanding_paisa": outstanding["outstanding_paisa"],
        "customers_owing": outstanding["customers_owing"],
        "entry_count": len(lines),
    }
