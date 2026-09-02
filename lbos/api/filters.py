"""Jinja filters. Presentation only - no rounding decisions happen here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from lbos.domain.money import format_paisa
from lbos.domain.quantity import format_milli, from_milli

DOC_TYPE_LABEL = {
    "sale": "Sale / বিক্রয়",
    "purchase": "Purchase / ক্রয়",
    "stock": "Stock / মজুদ",
    "memo": "Note / নোট",
}

STATUS_LABEL = {
    "pending_review": "Needs review",
    "posted": "Recorded",
    "rejected": "Discarded",
}


def taka(paisa: Any) -> str:
    try:
        return format_paisa(int(paisa or 0))
    except (TypeError, ValueError):
        return "—"


def taka_plain(paisa: Any) -> str:
    """Amount without the currency symbol, for prefilling a form input."""
    try:
        return f"{int(paisa or 0) / 100:.2f}"
    except (TypeError, ValueError):
        return ""


def qty(milli: Any, unit: str | None = None) -> str:
    try:
        return format_milli(int(milli or 0), unit)
    except (TypeError, ValueError):
        return "—"


def qty_plain(milli: Any) -> str:
    try:
        return format(from_milli(int(milli or 0)).normalize(), "f")
    except (TypeError, ValueError):
        return ""


def when(value: Any) -> str:
    """Render a stored UTC timestamp compactly."""
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def doc_type_label(value: Any) -> str:
    return DOC_TYPE_LABEL.get(str(value), str(value))


def status_label(value: Any) -> str:
    return STATUS_LABEL.get(str(value), str(value))


def percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


FILTERS = {
    "taka": taka,
    "taka_plain": taka_plain,
    "qty": qty,
    "qty_plain": qty_plain,
    "when": when,
    "doc_type_label": doc_type_label,
    "status_label": status_label,
    "percent": percent,
}
