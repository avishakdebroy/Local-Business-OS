"""Combining the rules reader with the optional model reader."""

from __future__ import annotations

from datetime import date

from lbos.domain.entities import Extraction
from lbos.domain.money import format_paisa
from lbos.interpretation import llm, rules
from lbos.settings import Settings

#: Fields that must be present before an entry can reach the books unattended.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "sale": ("entry_date", "total_paisa"),
    "purchase": ("entry_date", "total_paisa"),
    "stock": ("entry_date", "lines"),
    "memo": ("entry_date", "body"),
}


def _merge(base: Extraction, other: Extraction) -> Extraction:
    """Fold the model's reading into the rules reading.

    Agreement raises confidence a little; disagreement lowers it a lot. The two
    readers disagreeing is exactly the case a human should look at.
    """
    if other.doc_type != base.doc_type:
        base.notes.append(
            f"The built-in reader saw a {base.doc_type} and the AI saw a "
            f"{other.doc_type}. Please confirm which is right."
        )
        base.confidence = min(base.confidence, 0.45)
        base.extractor = "rules+llm"
        return base

    filled: list[str] = []
    for key, value in other.fields.items():
        if value in (None, "", [], 0) and key != "tax_paisa":
            continue
        if base.fields.get(key) in (None, "", []):
            base.fields[key] = value
            filled.append(key)

    base_total = base.fields.get("total_paisa")
    other_total = other.fields.get("total_paisa")
    if base_total is not None and other_total is not None:
        if base_total == other_total:
            base.confidence = min(0.97, base.confidence + 0.08)
        else:
            base.notes.append(
                f"The built-in reader read the total as {format_paisa(base_total)} "
                f"and the AI read {format_paisa(other_total)}. Please check."
            )
            base.confidence = min(base.confidence, 0.45)

    if filled:
        base.notes.append("AI filled in: " + ", ".join(sorted(filled)) + ".")
    base.extractor = "rules+llm"
    return base


def interpret(
    text: str,
    settings: Settings,
    hint: str = "auto",
    today: date | None = None,
) -> Extraction:
    """Read ``text`` into a proposed entry using whatever readers are available."""
    extraction = rules.extract(text, hint=hint, today=today)

    assisted = llm.extract(text, settings, hint=hint, today=today)
    if assisted is not None:
        extraction = _merge(extraction, assisted)

    return extraction


def blocking_gaps(extraction: Extraction) -> list[str]:
    """Required fields this extraction is still missing."""
    required = REQUIRED_FIELDS.get(extraction.doc_type, ())
    missing = []
    for key in required:
        value = extraction.fields.get(key)
        if value in (None, "", []):
            missing.append(key)
    if extraction.doc_type == "stock":
        lines = extraction.fields.get("lines") or []
        if any(not line.get("direction") for line in lines):
            missing.append("lines.direction")
    return missing


def decide_status(extraction: Extraction, settings: Settings) -> str:
    """``posted`` if it can be trusted unattended, otherwise ``pending_review``.

    Confidence alone is not enough: an entry missing a required field is held
    back no matter how sure the reader was.
    """
    if blocking_gaps(extraction):
        return "pending_review"
    if extraction.confidence < settings.auto_post_threshold:
        return "pending_review"
    return "posted"
