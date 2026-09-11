"""Shared page context."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Request

from lbos.ledger import repositories as repo


def context(
    request: Request, conn: sqlite3.Connection, page: str, **extra: Any
) -> dict[str, Any]:
    """Base context every page needs, including the review badge count."""
    counts = repo.document_status_counts(conn)
    base: dict[str, Any] = {
        "request": request,
        "page": page,
        "pending_count": counts.get("pending_review", 0),
        "owed_count": repo.credit_totals(conn)["customers_owing"],
        "msg": request.query_params.get("msg"),
        "kind": request.query_params.get("kind", "ok"),
    }
    base.update(extra)
    return base
