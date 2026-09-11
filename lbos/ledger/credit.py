"""Customer credit — the বাকি খাতা.

A shop sells on credit to regulars all day and settles it in instalments. The
paper ledger answers one question above all others: *who owes me money?* This
module is the service layer for that, with the same rules as the rest of the
books — amounts validated before they land, entries voided rather than edited,
and the balance derived from entries so it can never disagree with its history.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lbos.db.connection import transaction
from lbos.domain.errors import NotFoundError, ValidationError
from lbos.domain.money import format_paisa
from lbos.domain.periods import iso, parse_iso_date
from lbos.ledger import repositories as repo

MAX_PAISA = 10**13

CHARGE = "charge"    # goods given on credit  — বাকি
PAYMENT = "payment"  # money received back    — জমা

KIND_LABELS = {
    CHARGE: "Credit given / বাকি",
    PAYMENT: "Payment received / জমা",
}


@dataclass
class CreditResult:
    customer_id: int
    entry_id: int
    balance_paisa: int
    message: str


def _require_amount(value: Any, label: str = "Amount") -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be an amount of money.") from None
    if amount <= 0:
        raise ValidationError(f"{label} must be more than zero.")
    if amount >= MAX_PAISA:
        raise ValidationError(f"{label} looks far too large ({format_paisa(amount)}).")
    return amount


def _require_date(value: Any) -> str:
    parsed = parse_iso_date(str(value or ""))
    if parsed is None:
        raise ValidationError("Date must be a real date in YYYY-MM-DD form.")
    return iso(parsed)


def _load(conn: sqlite3.Connection, customer_id: int) -> dict[str, Any]:
    row = repo.customer(conn, customer_id)
    if row is None:
        raise NotFoundError(f"Customer {customer_id} does not exist.")
    return row


def add_customer(
    conn: sqlite3.Connection, *, name: str, phone: str | None = None, note: str | None = None
) -> int:
    if not (name or "").strip():
        raise ValidationError("A customer needs a name.")
    with transaction(conn):
        return repo.upsert_customer(conn, name=name, phone=phone, note=note)


def record(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    kind: str,
    amount_paisa: Any,
    entry_date: Any,
    note: str | None = None,
    document_id: int | None = None,
) -> CreditResult:
    """Record credit given or a payment received."""
    if kind not in (CHARGE, PAYMENT):
        raise ValidationError(f"Unknown entry type: {kind}")

    row = _load(conn, customer_id)
    amount = _require_amount(
        amount_paisa, "Credit amount" if kind == CHARGE else "Payment amount"
    )
    when = _require_date(entry_date)

    # Overpayment is usually a typo, and silently creating a negative balance
    # hides it. Refuse, and say what the balance actually is.
    if kind == PAYMENT and amount > int(row["balance_paisa"]):
        raise ValidationError(
            f"{row['name']} owes {format_paisa(int(row['balance_paisa']))}, "
            f"but the payment entered is {format_paisa(amount)}. "
            "Enter the smaller amount, or record the extra as a separate sale."
        )

    with transaction(conn):
        entry_id = repo.insert_credit_entry(
            conn, customer_id=customer_id, entry_date=when, kind=kind,
            amount_paisa=amount, note=note, document_id=document_id,
        )

    balance = int(_load(conn, customer_id)["balance_paisa"])
    verb = "Credit recorded" if kind == CHARGE else "Payment recorded"
    return CreditResult(
        customer_id=customer_id,
        entry_id=entry_id,
        balance_paisa=balance,
        message=(
            f"{verb}. {row['name']} now owes {format_paisa(balance)}."
            if balance > 0
            else f"{verb}. {row['name']} is fully settled."
        ),
    )


def give_credit(conn: sqlite3.Connection, **kwargs: Any) -> CreditResult:
    return record(conn, kind=CHARGE, **kwargs)


def take_payment(conn: sqlite3.Connection, **kwargs: Any) -> CreditResult:
    return record(conn, kind=PAYMENT, **kwargs)


def void_entry(conn: sqlite3.Connection, entry_id: int, reason: str) -> None:
    with transaction(conn):
        if repo.void_credit_entry(conn, entry_id, reason) == 0:
            raise NotFoundError(f"Entry {entry_id} is not there, or was already removed.")


def statement(conn: sqlite3.Connection, customer_id: int) -> dict[str, Any]:
    """A customer's page: their balance and every entry, newest first."""
    row = _load(conn, customer_id)
    entries = repo.credit_entries(conn, customer_id)

    # A running balance read downwards, the way the paper page reads.
    running = int(row["balance_paisa"])
    for entry in entries:
        entry["balance_after"] = running
        running -= entry["amount_paisa"] if entry["kind"] == CHARGE else -entry["amount_paisa"]

    return {"customer": row, "entries": entries}
