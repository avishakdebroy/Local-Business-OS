"""A small JSON surface, for health checks and scripting."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends

from lbos.api.deps import get_conn, get_settings
from lbos.domain.periods import iso, local_today, week_window
from lbos.ledger import repositories as repo
from lbos.settings import Settings

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health(
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict:
    counts = repo.document_status_counts(conn)
    return {
        "status": "ok",
        "timezone": settings.timezone,
        "currency": settings.currency,
        "documents": counts,
        "failing_jobs": [row["job_name"] for row in repo.failing_jobs(conn)],
    }


@router.get("/summary")
def summary(
    days: int = 7,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict:
    days = max(1, min(days, 366))
    end = local_today(settings.timezone)
    start, end = week_window(settings.timezone, anchor=end, days=days)
    return {
        "period_start": iso(start),
        "period_end": iso(end),
        "currency": settings.currency,
        "totals_paisa": repo.money_totals(conn, iso(start), iso(end)),
        "low_stock": repo.stock_levels(conn, low_only=True),
        "pending_review": repo.document_status_counts(conn).get("pending_review", 0),
    }
