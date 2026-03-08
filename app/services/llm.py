from __future__ import annotations

import json
from typing import Any

import requests

from app.config import settings


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fallback_parse(text: str, requested_type: str) -> dict[str, Any]:
    low = text.lower()
    inferred = requested_type if requested_type != "auto" else "memo"
    if requested_type == "auto":
        if any(k in low for k in ["total", "invoice", "receipt", "vat"]):
            inferred = "receipt"
        elif any(k in low for k in ["stock", "inventory", "qty", "quantity"]):
            inferred = "inventory"

    payload: dict[str, Any] = {
        "document_type": inferred,
        "confidence": 0.35,
        "receipt": None,
        "inventory": None,
        "memo": None,
    }

    if inferred == "receipt":
        payload["receipt"] = {
            "date": None,
            "vendor": "Unknown",
            "total_amount": 0,
            "tax_amount": 0,
            "category": "general",
            "payment_method": "cash",
            "notes": text[:400],
        }
    elif inferred == "inventory":
        payload["inventory"] = {
            "sku": None,
            "name": "Unknown Item",
            "move_type": "in",
            "qty": 0,
            "unit": "pcs",
            "unit_cost": 0,
            "reorder_level": 0,
            "notes": text[:400],
        }
    else:
        payload["memo"] = {
            "title": "Memo",
            "body": text[:4000],
            "tags": "",
        }

    return payload


def parse_document_with_llm(text: str, requested_type: str = "auto") -> dict[str, Any]:
    if not settings.llm_enabled:
        return _fallback_parse(text, requested_type)

    prompt = f"""
You are an information extraction engine for a small business app.

Extract from the text below into ONE strict JSON object with exactly these top-level keys:
- document_type: one of [receipt, inventory, memo]
- confidence: number from 0 to 1
- receipt: object or null
- inventory: object or null
- memo: object or null

Rules:
- If requested_type is not auto, force document_type to that type.
- receipt fields: date, vendor, total_amount, tax_amount, category, payment_method, notes
- inventory fields: sku, name, move_type(in/out), qty, unit, unit_cost, reorder_level, notes
- memo fields: title, body, tags
- Return JSON only. No markdown.

requested_type: {requested_type}
text:
{text[:8000]}
""".strip()

    try:
        response = requests.post(
            f"{settings.llm_base_url.rstrip('/')}/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        parsed = json.loads(raw)

        parsed.setdefault("document_type", requested_type if requested_type != "auto" else "memo")
        parsed["confidence"] = _safe_number(parsed.get("confidence"), 0.5)
        parsed.setdefault("receipt", None)
        parsed.setdefault("inventory", None)
        parsed.setdefault("memo", None)
        return parsed
    except Exception:
        return _fallback_parse(text, requested_type)
