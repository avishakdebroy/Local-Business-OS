"""Reading review-screen forms back into ledger fields.

Amounts are typed in taka because that is what is written on the paper; they are
converted to integer paisa here, once, at the edge.
"""

from __future__ import annotations

from typing import Any

from starlette.datastructures import FormData

from lbos.domain.errors import ValidationError
from lbos.domain.money import Money
from lbos.domain.quantity import canonical_unit, to_milli


def _text(form: FormData, key: str) -> str | None:
    value = form.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _paisa(form: FormData, key: str, label: str, *, required: bool) -> int | None:
    raw = _text(form, key)
    if raw is None:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    try:
        return Money.from_taka(raw).paisa
    except (ValueError, ArithmeticError):
        raise ValidationError(f"{label}: “{raw}” is not an amount of money.") from None


def money_fields(form: FormData) -> dict[str, Any]:
    return {
        "entry_date": _text(form, "entry_date"),
        "party": _text(form, "party"),
        "total_paisa": _paisa(form, "total", "Amount", required=True),
        "tax_paisa": _paisa(form, "tax", "VAT", required=False) or 0,
        "category": _text(form, "category"),
        "payment_method": _text(form, "payment_method"),
        "notes": _text(form, "notes"),
    }


def stock_fields(form: FormData) -> dict[str, Any]:
    names = form.getlist("line_name")
    quantities = form.getlist("line_qty")
    units = form.getlist("line_unit")
    directions = form.getlist("line_direction")
    costs = form.getlist("line_cost")

    lines: list[dict[str, Any]] = []
    for index in range(len(names)):
        name = str(names[index]).strip()
        raw_qty = str(quantities[index]).strip() if index < len(quantities) else ""
        # A row left entirely blank is simply not a row.
        if not name and not raw_qty:
            continue

        qty_milli = to_milli(raw_qty)
        if qty_milli is None:
            raise ValidationError(f"Line {index + 1}: “{raw_qty}” is not a quantity.")

        raw_cost = str(costs[index]).strip() if index < len(costs) else ""
        unit_cost = None
        if raw_cost:
            try:
                unit_cost = Money.from_taka(raw_cost).paisa
            except (ValueError, ArithmeticError):
                raise ValidationError(
                    f"Line {index + 1}: “{raw_cost}” is not an amount of money."
                ) from None

        lines.append(
            {
                "name": name,
                "qty_milli": qty_milli,
                "unit": canonical_unit(units[index] if index < len(units) else None),
                "direction": (directions[index] if index < len(directions) else "").strip().lower(),
                "unit_cost_paisa": unit_cost,
            }
        )

    return {
        "entry_date": _text(form, "entry_date"),
        "lines": lines,
        "notes": _text(form, "notes"),
    }


def memo_fields(form: FormData) -> dict[str, Any]:
    return {
        "entry_date": _text(form, "entry_date"),
        "title": _text(form, "title"),
        "body": _text(form, "body") or "",
        "tags": _text(form, "tags") or "",
    }


def fields_for(doc_type: str, form: FormData) -> dict[str, Any]:
    if doc_type in ("sale", "purchase"):
        return money_fields(form)
    if doc_type == "stock":
        return stock_fields(form)
    if doc_type == "memo":
        return memo_fields(form)
    raise ValidationError(f"Unknown entry type: {doc_type}")
