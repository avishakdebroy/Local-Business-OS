"""Typed carriers passed between layers, plus the vocabulary they share."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

# --- Vocabulary -------------------------------------------------------------

DocType = Literal["sale", "purchase", "stock", "memo"]
DOC_TYPES: tuple[str, ...] = ("sale", "purchase", "stock", "memo")

#: Money entries. Both land in ``receipts``; ``direction`` says which way.
MONEY_TYPES: tuple[str, ...] = ("sale", "purchase")

DocStatus = Literal["pending_review", "posted", "rejected"]
DOC_STATUSES: tuple[str, ...] = ("pending_review", "posted", "rejected")

StockDirection = Literal["in", "out"]
STOCK_DIRECTIONS: tuple[str, ...] = ("in", "out")

#: Payment methods a Bangladeshi shop actually uses.
PAYMENT_METHODS: tuple[str, ...] = (
    "cash", "bkash", "nagad", "rocket", "card", "bank", "due",
)

DOC_TYPE_LABELS: dict[str, str] = {
    "sale": "Sale / বিক্রয়",
    "purchase": "Purchase / ক্রয়",
    "stock": "Stock / মজুদ",
    "memo": "Note / নোট",
}


# --- Extraction -------------------------------------------------------------


@dataclass
class Extraction:
    """What the interpretation layer believes a document says.

    This is a *proposal*. Nothing here reaches the ledger until it either clears
    the confidence threshold or a human accepts it on the review screen.
    """

    doc_type: str
    confidence: float
    fields: dict[str, Any] = field(default_factory=dict)
    extractor: str = "rules"
    notes: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def missing(self, keys: tuple[str, ...]) -> list[str]:
        return [k for k in keys if self.fields.get(k) in (None, "")]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "doc_type": self.doc_type,
            "confidence": round(float(self.confidence), 4),
            "extractor": self.extractor,
            "fields": self.fields,
            "notes": self.notes,
        }


# --- Records ----------------------------------------------------------------


@dataclass
class Document:
    id: int
    content_hash: str
    source_kind: str
    doc_type: str
    status: str
    confidence: float
    raw_text: str
    extraction: dict[str, Any]
    extractor: str
    captured_at: str
    original_filename: str | None = None
    stored_path: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None


@dataclass
class CaptureResult:
    """Outcome of taking one document in."""

    document_id: int
    doc_type: str
    status: str
    confidence: float
    duplicate_of: int | None = None
    message: str = ""

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None

    @property
    def needs_review(self) -> bool:
        return self.status == "pending_review"


@dataclass
class MoneyEntry:
    """A sale or purchase as the ledger holds it."""

    id: int
    document_id: int
    entry_date: date
    direction: str
    party: str | None
    total_paisa: int
    tax_paisa: int
    currency: str
    category: str | None
    payment_method: str | None
    notes: str | None
    voided_at: str | None = None


@dataclass
class StockLine:
    """One item with its derived on-hand quantity."""

    item_id: int
    sku: str | None
    name: str
    unit: str
    on_hand_milli: int
    reorder_level_milli: int

    @property
    def is_low(self) -> bool:
        return self.on_hand_milli <= self.reorder_level_milli
