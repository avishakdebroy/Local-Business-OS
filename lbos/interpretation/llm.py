"""Optional local-model assist via Ollama.

This is strictly an *enhancement*. It is off by default, it never runs when the
model is unreachable, and it never bypasses review: its output is merged into
the rules result and disagreement between the two lowers confidence rather than
raising it. A shop with no GPU and no Ollama install loses nothing but a little
accuracy.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from lbos.domain.entities import Extraction
from lbos.domain.money import Money, parse_taka_decimal
from lbos.domain.periods import iso, parse_date
from lbos.domain.quantity import canonical_unit, to_milli
from lbos.settings import Settings

PROMPT = """You extract bookkeeping data for a small shop in Bangladesh.

Return ONE JSON object and nothing else. Use these keys exactly:

{{
  "doc_type": "sale" | "purchase" | "stock" | "memo",
  "confidence": 0.0 to 1.0,
  "entry_date": "YYYY-MM-DD" or null,
  "party": string or null,
  "total": number or null,          // in taka, not paisa
  "tax": number or null,            // in taka
  "category": string or null,
  "payment_method": "cash"|"bkash"|"nagad"|"rocket"|"card"|"bank"|"due"|null,
  "title": string or null,          // for memo
  "lines": [                        // for stock only, else []
    {{"name": string, "qty": number, "unit": string,
      "direction": "in"|"out", "unit_cost": number or null}}
  ]
}}

Rules:
- "sale" is money coming in, "purchase" is money going out.
- Use null when the text does not say. Never invent a number.
- The text may be in Bengali, English, or both.
{type_rule}
TEXT:
{text}
"""


def _coerce_money_paisa(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Money.from_taka(value).paisa
        except Exception:
            return None
    decimal_value = parse_taka_decimal(str(value))
    return Money.from_taka(decimal_value).paisa if decimal_value is not None else None


def _coerce_lines(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in value[:50]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        qty_milli = to_milli(raw.get("qty"))
        if not name or not qty_milli or qty_milli <= 0:
            continue
        direction = str(raw.get("direction") or "").strip().lower()
        out.append(
            {
                "name": name[:120],
                "qty_milli": qty_milli,
                "unit": canonical_unit(raw.get("unit")),
                "direction": direction if direction in ("in", "out") else None,
                "unit_cost_paisa": _coerce_money_paisa(raw.get("unit_cost")),
            }
        )
    return out


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.4
    return max(0.0, min(number, 1.0))


def extract(
    text: str,
    settings: Settings,
    hint: str = "auto",
    today: date | None = None,
) -> Extraction | None:
    """Ask the local model to read ``text``. Returns None if unavailable."""
    if not settings.llm_enabled or not (text or "").strip():
        return None

    reference = today or date.today()
    type_rule = (
        f'- The operator says this is a "{hint}". Use that as doc_type.\n'
        if hint in ("sale", "purchase", "stock", "memo")
        else ""
    )
    prompt = PROMPT.format(type_rule=type_rule, text=text[:8000])

    try:
        import requests

        response = requests.post(
            f"{settings.llm_base_url.rstrip('/')}/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = json.loads(response.json().get("response") or "{}")
        if not isinstance(payload, dict):
            return None
    except Exception:
        # Model down, timed out, or spoke nonsense. The rules result stands.
        return None

    doc_type = str(payload.get("doc_type") or "").strip().lower()
    if doc_type not in ("sale", "purchase", "stock", "memo"):
        return None

    parsed_date = parse_date(str(payload.get("entry_date") or ""), today=reference)
    fields: dict[str, Any] = {"entry_date": iso(parsed_date) if parsed_date else None}

    if doc_type in ("sale", "purchase"):
        party = payload.get("party")
        payment = str(payload.get("payment_method") or "").strip().lower() or None
        fields.update(
            {
                "direction": doc_type,
                "party": str(party).strip()[:120] if party else None,
                "total_paisa": _coerce_money_paisa(payload.get("total")),
                "tax_paisa": _coerce_money_paisa(payload.get("tax")) or 0,
                "category": (str(payload.get("category")).strip()[:40] or None)
                if payload.get("category")
                else None,
                "payment_method": payment
                if payment in ("cash", "bkash", "nagad", "rocket", "card", "bank", "due")
                else None,
            }
        )
    elif doc_type == "stock":
        fields["lines"] = _coerce_lines(payload.get("lines"))
    else:
        title = payload.get("title")
        fields.update(
            {
                "title": (str(title).strip()[:80] if title else None) or "Note",
                "body": text,
                "tags": "",
            }
        )

    return Extraction(
        doc_type=doc_type,
        confidence=_coerce_confidence(payload.get("confidence")),
        fields=fields,
        extractor="llm",
        notes=[],
    )
