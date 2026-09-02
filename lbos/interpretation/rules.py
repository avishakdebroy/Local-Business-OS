"""Deterministic extraction: the primary reader.

This runs with no network, no model and no GPU, which is what makes the app
usable on a shop counter PC. It is deliberately conservative - when a cue is
missing it lowers its own confidence rather than inventing a value, and low
confidence sends the document to the review screen instead of to the books.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from lbos.domain.entities import Extraction
from lbos.domain.money import Money, format_paisa
from lbos.domain.periods import iso, parse_date
from lbos.domain.quantity import UNIT_ALIASES, canonical_unit, to_milli
from lbos.interpretation.normalize import Analysis, analyse
from lbos.interpretation.vocabulary import (
    CATEGORY_WORDS,
    MONEY_WORDS,
    PARTY_LABELS,
    PAYMENT_WORDS,
    PURCHASE_WORDS,
    SALE_WORDS,
    STOCK_IN_WORDS,
    STOCK_OUT_WORDS,
    STOCK_WORDS,
    TOTAL_WORDS,
    VAT_WORDS,
    first_mapped,
    hits,
    spans as word_spans,
)

_NUM = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_DATE_LIKE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}\b")
_TIME_LIKE = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?|\b\d{1,2}\s*(?:am|pm)\b",
    re.IGNORECASE,
)
_CURRENCY = re.compile(r"৳|tk\.?|bdt|taka|টাকা|/-", re.IGNORECASE)
_SERIAL_PREFIX = re.compile(
    r"(?:#|no\.?|sl\.?|serial|ref|phone|mobile|mob|imei|acct?|account)\s*[:.]?\s*$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-zঀ-৿]")
_UNIT_AFTER = re.compile(r"\s*([A-Za-zঀ-৿]{1,10})\.?")
_UNIT_COST = re.compile(r"@\s*([\d,]+(?:\.\d+)?)")

_KNOWN_UNITS = set(UNIT_ALIASES)

#: Bare integers at least this long are treated as phone numbers or serials.
_MAX_AMOUNT_DIGITS = 9

MONEY_REQUIRED = ("total_paisa", "entry_date")
STOCK_REQUIRED = ("lines", "entry_date")


# --- Amount scanning --------------------------------------------------------


@dataclass(frozen=True)
class _Amount:
    value: Decimal
    currency_marked: bool
    start: int


def _mask(text: str) -> str:
    """Blank out dates and times so their digits cannot be read as money."""
    masked = _DATE_LIKE.sub(lambda m: " " * len(m.group(0)), text)
    return _TIME_LIKE.sub(lambda m: " " * len(m.group(0)), masked)


def amounts_in(line: str) -> list[_Amount]:
    """Every number on ``line`` that could plausibly be an amount of money."""
    masked = _mask(line)
    found: list[_Amount] = []

    for match in _NUM.finditer(masked):
        token = match.group(0)
        digits = token.replace(",", "").replace(".", "")

        # Phone numbers, invoice numbers, national IDs.
        if "." not in token and "," not in token and len(digits) >= _MAX_AMOUNT_DIGITS:
            continue
        before = masked[max(0, match.start() - 12):match.start()]
        if _SERIAL_PREFIX.search(before):
            continue

        # A number followed by a unit is a quantity, not a price.
        after = masked[match.end():match.end() + 12]
        unit_match = _UNIT_AFTER.match(after)
        if unit_match and unit_match.group(1).lower() in _KNOWN_UNITS:
            continue

        window = before[-8:] + masked[match.end():match.end() + 8]
        try:
            value = Decimal(token.replace(",", ""))
        except Exception:
            continue
        found.append(_Amount(value, bool(_CURRENCY.search(window)), match.start()))

    return found


def _pick_total(a: Analysis) -> tuple[Money | None, bool]:
    """Return the document total and whether it was found on a labelled line."""
    for line, folded in zip(reversed(a.lines), reversed(a.folded_lines)):
        if not any(word in folded for word in TOTAL_WORDS):
            continue
        candidates = amounts_in(line)
        if candidates:
            return Money.from_taka(max(c.value for c in candidates)), True

    everything = [amt for line in a.lines for amt in amounts_in(line)]
    if not everything:
        return None, False
    marked = [amt for amt in everything if amt.currency_marked]
    pool = marked or everything
    return Money.from_taka(max(amt.value for amt in pool)), False


def _pick_vat(a: Analysis, total: Money | None) -> Money | None:
    for line, folded in zip(a.lines, a.folded_lines):
        if not any(word in folded for word in VAT_WORDS):
            continue
        candidates = amounts_in(line)
        if not candidates:
            continue
        vat = Money.from_taka(min(c.value for c in candidates))
        if total is None or vat.paisa <= total.paisa:
            return vat
    return None


def _pick_party(a: Analysis) -> str | None:
    """Who the money went to or came from."""
    for line, folded in zip(a.lines, a.folded_lines):
        match = re.match(r"\s*([^:]{1,24})\s*[:\-]\s*(.+)$", line)
        if not match:
            continue
        label = match.group(1).strip().casefold()
        if any(label == p or label.startswith(p) for p in PARTY_LABELS):
            value = match.group(2).strip(" .,-")
            if _WORD.search(value):
                return value[:120]

    # Fall back to a heading-like first line: words, no money, not a total row.
    for line, folded in zip(a.lines[:3], a.folded_lines[:3]):
        if amounts_in(line):
            continue
        if any(word in folded for word in TOTAL_WORDS + VAT_WORDS):
            continue
        if len(_WORD.findall(line)) >= 3:
            return line.strip(" .,-:")[:120]
    return None


# --- Stock lines ------------------------------------------------------------


@dataclass
class StockDraft:
    name: str
    qty_milli: int
    unit: str
    direction: str | None
    unit_cost_paisa: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qty_milli": self.qty_milli,
            "unit": self.unit,
            "direction": self.direction,
            "unit_cost_paisa": self.unit_cost_paisa,
        }


def _direction_of(folded: str) -> str | None:
    out_score = len(hits(folded, STOCK_OUT_WORDS))
    in_score = len(hits(folded, STOCK_IN_WORDS))
    if out_score > in_score:
        return "out"
    if in_score > out_score:
        return "in"
    return None


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    """Remove character spans from ``text`` and tidy the leftovers."""
    kept = list(text)
    for start, end in spans:
        for i in range(max(0, start), min(len(kept), end)):
            kept[i] = " "
    return re.sub(r"\s{2,}", " ", "".join(kept)).strip(" .,-:;|@x*")


def parse_stock_line(line: str, strict: bool = True) -> StockDraft | None:
    """Read one line such as ``received 20 kg miniket rice @ 62``.

    In strict mode a line must carry a recognised unit or an in/out cue to
    count as stock. Without that guard any sentence containing a number - "reopen
    tomorrow 9am" - would be filed as a stock movement.
    """
    if not line.strip():
        return None

    lowered = line.lower()
    if len(lowered) != len(line):  # casing changed the length; skip cue removal
        lowered = line

    spans: list[tuple[int, int]] = []

    unit_cost_paisa = None
    cost_match = _UNIT_COST.search(line)
    if cost_match:
        unit_cost_paisa = Money.from_taka(cost_match.group(1)).paisa
        spans.append(cost_match.span())

    masked = _mask(line if not cost_match else _cut_preserve(line, cost_match.span()))
    qty_match = _NUM.search(masked)
    if not qty_match:
        return None
    qty_milli = to_milli(qty_match.group(0))
    if not qty_milli or qty_milli <= 0:
        return None
    spans.append(qty_match.span())

    unit = None
    unit_match = _UNIT_AFTER.match(masked[qty_match.end():])
    if unit_match and unit_match.group(1).lower() in _KNOWN_UNITS:
        unit = canonical_unit(unit_match.group(1))
        offset = qty_match.end()
        spans.append((offset + unit_match.start(1), offset + unit_match.end(1)))

    direction = _direction_of(lowered)
    if strict and unit is None and direction is None:
        return None

    for word in STOCK_IN_WORDS + STOCK_OUT_WORDS + STOCK_WORDS:
        spans.extend(word_spans(lowered, word))

    name = _cut(line, spans)
    name = re.sub(r"^(?:of|for|the|a|an)\s+", "", name, flags=re.IGNORECASE).strip()
    if not name or not _WORD.search(name):
        return None

    return StockDraft(
        name=name[:120],
        qty_milli=qty_milli,
        unit=unit or "pcs",
        direction=direction,
        unit_cost_paisa=unit_cost_paisa,
    )


def _cut_preserve(text: str, span: tuple[int, int]) -> str:
    return text[:span[0]] + " " * (span[1] - span[0]) + text[span[1]:]


def parse_stock_lines(a: Analysis, strict: bool = True) -> list[StockDraft]:
    drafts = [d for d in (parse_stock_line(line, strict) for line in a.lines) if d]
    if not drafts and a.text:
        single = parse_stock_line(a.text.replace("\n", " "), strict)
        if single:
            drafts = [single]

    document_direction = _direction_of(a.folded)
    for draft in drafts:
        if draft.direction is None:
            draft.direction = document_direction
    return drafts


# --- Classification ---------------------------------------------------------


@dataclass
class _Signals:
    money: int = 0
    sale: int = 0
    purchase: int = 0
    stock: int = 0
    has_amount: bool = False
    stock_line_count: int = 0


def _signals(a: Analysis, drafts: list[StockDraft]) -> _Signals:
    return _Signals(
        money=len(hits(a.folded, MONEY_WORDS)),
        sale=len(hits(a.folded, SALE_WORDS)),
        purchase=len(hits(a.folded, PURCHASE_WORDS)),
        stock=len(hits(a.folded, STOCK_WORDS)),
        has_amount=any(amounts_in(line) for line in a.lines),
        stock_line_count=len(drafts),
    )


def classify(a: Analysis, signals: _Signals, hint: str) -> tuple[str, list[str]]:
    """Decide the document type. Returns the type and any caveats."""
    notes: list[str] = []

    stock_score = 2 * signals.stock + (3 if signals.stock_line_count else 0)
    money_score = signals.money + (2 if signals.has_amount else 0)

    if hint in ("sale", "purchase", "stock", "memo"):
        return hint, ["Type chosen by the operator."]

    if not a.text:
        return "memo", ["The document had no readable text."]

    if stock_score > money_score and signals.stock_line_count:
        return "stock", notes

    if money_score >= 3 or (signals.has_amount and signals.money >= 1):
        if signals.sale > signals.purchase:
            return "sale", notes
        if signals.purchase > signals.sale:
            return "purchase", notes
        notes.append(
            "The document does not say whether this is a sale or a purchase - "
            "please confirm."
        )
        return "purchase", notes

    if signals.has_amount and signals.money:
        notes.append("An amount was found but the document type was unclear.")
        return "purchase", notes

    return "memo", notes


# --- Field extraction -------------------------------------------------------


def _money_fields(a: Analysis, doc_type: str, today: date) -> tuple[dict[str, Any], dict[str, Any]]:
    total, labelled = _pick_total(a)
    vat = _pick_vat(a, total)
    party = _pick_party(a)
    payment = first_mapped(a.folded, PAYMENT_WORDS)
    category = first_mapped(a.folded, CATEGORY_WORDS)
    found_date = parse_date(a.text, today=today)

    fields: dict[str, Any] = {
        "direction": doc_type,
        "entry_date": iso(found_date or today),
        "party": party,
        "total_paisa": total.paisa if total else None,
        "tax_paisa": vat.paisa if vat else 0,
        "category": category,
        "payment_method": payment,
        "notes": None,
    }
    cues = {
        "labelled_total": labelled,
        "date_in_text": found_date is not None,
        "party_found": party is not None,
        "payment_found": payment is not None,
        "vat_found": vat is not None,
    }
    return fields, cues


def _stock_fields(a: Analysis, drafts: list[StockDraft], today: date) -> tuple[dict[str, Any], dict[str, Any]]:
    found_date = parse_date(a.text, today=today)
    fields: dict[str, Any] = {
        "entry_date": iso(found_date or today),
        "lines": [d.to_dict() for d in drafts],
        "notes": None,
    }
    cues = {
        "date_in_text": found_date is not None,
        "line_count": len(drafts),
        "all_directed": bool(drafts) and all(d.direction for d in drafts),
        "units_known": bool(drafts) and all(d.unit != "pcs" or "pcs" in a.folded for d in drafts),
    }
    return fields, cues


def _memo_fields(a: Analysis, today: date) -> dict[str, Any]:
    first_line = a.lines[0] if a.lines else "Note"
    found_date = parse_date(a.text, today=today)
    tags = sorted({v for v in (first_mapped(a.folded, CATEGORY_WORDS),) if v})
    return {
        "entry_date": iso(found_date or today),
        "title": first_line[:80] or "Note",
        "body": a.text,
        "tags": ",".join(tags),
    }


# --- Confidence -------------------------------------------------------------


def _money_confidence(cues: dict[str, Any], fields: dict[str, Any], notes: list[str], hinted: bool) -> float:
    score = 0.30
    if fields["total_paisa"] is None:
        # Without an amount there is nothing to post; force a human look.
        return 0.20
    score += 0.30 if cues["labelled_total"] else 0.12
    score += 0.12 if cues["date_in_text"] else 0.0
    score += 0.10 if cues["party_found"] else 0.0
    score += 0.08 if cues["payment_found"] else 0.0
    score += 0.05 if cues["vat_found"] else 0.0
    if hinted:
        score += 0.10
    ceiling = 0.97
    if any("sale or a purchase" in n for n in notes):
        ceiling = 0.60
    return max(0.0, min(score, ceiling))


def _stock_confidence(cues: dict[str, Any], notes: list[str], hinted: bool) -> float:
    if not cues["line_count"]:
        return 0.20
    score = 0.35
    score += 0.30 if cues["all_directed"] else 0.05
    score += 0.12 if cues["date_in_text"] else 0.0
    score += 0.08 if cues["units_known"] else 0.0
    if hinted:
        score += 0.10
    if cues["line_count"] > 1:
        score -= 0.05  # multi-line notes are more often misread
    return max(0.0, min(score, 0.95))


def _memo_confidence(a: Analysis, signals: _Signals, hinted: bool) -> float:
    if hinted:
        return 0.95
    if not a.text:
        return 0.10
    if signals.has_amount or signals.money:
        # It looked financial but nothing parsed - do not bury it as a note.
        return 0.45
    return 0.88


# --- Entry point ------------------------------------------------------------


def extract(text: str, hint: str = "auto", today: date | None = None) -> Extraction:
    """Read ``text`` into a proposed entry. Never raises."""
    reference = today or date.today()
    try:
        return _extract(text, hint, reference)
    except Exception as exc:  # pragma: no cover - safety net
        return Extraction(
            doc_type="memo",
            confidence=0.0,
            fields={
                "entry_date": iso(reference),
                "title": "Could not be read",
                "body": text or "",
                "tags": "",
            },
            extractor="rules",
            notes=[f"Automatic reading failed ({type(exc).__name__}); please fill this in."],
        )


def _extract(text: str, hint: str, today: date) -> Extraction:
    a = analyse(text)
    # An explicit "stock" choice from the operator is itself the missing signal.
    drafts = parse_stock_lines(a, strict=hint != "stock")
    signals = _signals(a, drafts)
    doc_type, notes = classify(a, signals, hint)
    hinted = hint in ("sale", "purchase", "stock", "memo")

    if doc_type in ("sale", "purchase"):
        fields, cues = _money_fields(a, doc_type, today)
        confidence = _money_confidence(cues, fields, notes, hinted)
        if fields["total_paisa"] is None:
            notes.append("No amount could be found - please type it in.")
        elif not cues["labelled_total"]:
            notes.append(
                "No line was labelled 'total', so the largest amount "
                f"({format_paisa(fields['total_paisa'])}) was used."
            )
    elif doc_type == "stock":
        fields, cues = _stock_fields(a, drafts, today)
        confidence = _stock_confidence(cues, notes, hinted)
        if not cues["all_directed"]:
            notes.append("Could not tell whether stock came in or went out.")
    else:
        fields = _memo_fields(a, today)
        cues = {}
        confidence = _memo_confidence(a, signals, hinted)

    if not cues.get("date_in_text", True):
        notes.append("No date was found; today's date was used.")

    return Extraction(
        doc_type=doc_type,
        confidence=round(confidence, 4),
        fields=fields,
        extractor="rules",
        notes=notes,
    )
