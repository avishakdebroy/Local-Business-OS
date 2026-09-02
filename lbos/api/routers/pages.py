"""Home, ledger, stock, reports and status screens."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from lbos.api.deps import get_conn, get_settings
from lbos.api.routers.common import context
from lbos.api.templating import redirect, templates
from lbos.domain.errors import ConflictError, NotFoundError
from lbos.domain.periods import iso, local_today, parse_iso_date, week_window
from lbos.domain.quantity import to_milli
from lbos.ledger import posting
from lbos.ledger import repositories as repo
from lbos.ops.backup import free_space_bytes, run_backup
from lbos.reporting.weekly import run_weekly_report
from lbos.settings import Settings

router = APIRouter(tags=["pages"])


def _human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# --- Home -------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    today = local_today(settings.timezone)
    week_start, week_end = week_window(settings.timezone, anchor=today)

    return templates.TemplateResponse(
        request,
        "home.html",
        context(
            request, conn, "home",
            today=iso(today),
            today_totals=repo.money_totals(conn, iso(today), iso(today)),
            week_totals=repo.money_totals(conn, iso(week_start), iso(week_end)),
            week_start=iso(week_start),
            week_end=iso(week_end),
            low_stock=repo.stock_levels(conn, low_only=True)[:8],
            recent=repo.recent_documents(conn, limit=12),
        ),
    )


# --- Ledger -----------------------------------------------------------------


@router.get("/ledger", response_class=HTMLResponse)
def ledger(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    direction: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    today = local_today(settings.timezone)
    end_date = parse_iso_date(end) or today
    start_date = parse_iso_date(start) or (end_date - timedelta(days=29))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    direction = direction if direction in ("sale", "purchase") else None

    start_iso, end_iso = iso(start_date), iso(end_date)
    return templates.TemplateResponse(
        request,
        "ledger.html",
        context(
            request, conn, "ledger",
            start=start_iso, end=end_iso, direction=direction,
            totals=repo.money_totals(conn, start_iso, end_iso),
            entries=repo.money_entries(conn, start_iso, end_iso, direction=direction),
            memos=repo.memos(conn, start_iso, end_iso, limit=20),
        ),
    )


@router.post("/ledger/{document_id}/undo")
def undo_entry(
    document_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        posting.unpost(conn, document_id, "Taken back out of the books by the operator.")
    except (NotFoundError, ConflictError) as exc:
        return redirect("/ledger", str(exc), "error")
    return redirect(
        f"/review/{document_id}",
        f"Entry {document_id} was taken out of the books and is waiting for you here.",
        "warn",
    )


# --- Stock ------------------------------------------------------------------


@router.get("/stock", response_class=HTMLResponse)
def stock(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return templates.TemplateResponse(
        request,
        "stock.html", context(request, conn, "stock", levels=repo.stock_levels(conn))
    )


@router.get("/stock/{item_id}", response_class=HTMLResponse)
def stock_item(
    item_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    levels = repo.stock_levels(conn)
    item = next((row for row in levels if row["item_id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="That item does not exist.")
    return templates.TemplateResponse(
        request,
        "stock.html",
        context(
            request, conn, "stock",
            levels=levels, item=item, moves=repo.stock_moves(conn, item_id=item_id),
        ),
    )


@router.post("/stock/{item_id}/reorder")
def set_reorder(
    item_id: int,
    reorder_level: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    milli = to_milli(reorder_level or "0")
    if milli is None or milli < 0:
        return redirect("/stock", f"“{reorder_level}” is not a quantity.", "error")
    repo.set_reorder_level(conn, item_id, milli)
    conn.commit()
    return redirect("/stock", "Reorder level saved.", "ok")


# --- Reports ----------------------------------------------------------------


def _report_text(run: dict[str, Any]) -> str:
    path = run.get("report_path")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8", errors="replace")
    return "The report file is no longer on disk."


@router.get("/reports", response_class=HTMLResponse)
def reports(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    latest = repo.latest_report_run(conn)
    return templates.TemplateResponse(
        request,
        "reports.html",
        context(
            request, conn, "reports",
            runs=repo.report_runs(conn, limit=30),
            latest_text=_report_text(latest) if latest else None,
            report_day=settings.report_day,
            report_time=f"{settings.report_hour:02d}:{settings.report_minute:02d}",
        ),
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(
    report_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    runs = repo.report_runs(conn, limit=200)
    run = next((row for row in runs if row["id"] == report_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="That report does not exist.")
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        context(request, conn, "reports", run=run, text=_report_text(run)),
    )


@router.post("/reports/run")
def run_report_now(
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    result = run_weekly_report(conn, settings)
    note = {"sent": "It was emailed.", "skipped": "Email is not set up.",
            "failed": "The email could not be sent."}.get(result["delivery_status"], "")
    return redirect("/reports", f"Report made for {result['period_start']} → {result['period_end']}. {note}", "ok")


# --- Status -----------------------------------------------------------------


@router.get("/status", response_class=HTMLResponse)
def status(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    problems: list[str] = []

    ocr_status = "off (photos are stored but not read)"
    if settings.ocr_enabled:
        try:
            import pytesseract

            if settings.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
            ocr_status = f"working (Tesseract {pytesseract.get_tesseract_version()})"
        except Exception:
            ocr_status = "on, but Tesseract was not found — photos must be typed in"
            problems.append(
                "Photo reading is switched on but Tesseract is not installed. "
                "Install it, or set LBOS_TESSERACT_CMD to its full path."
            )

    llm_status = "off (not needed)"
    if settings.llm_enabled:
        try:
            import requests

            requests.get(f"{settings.llm_base_url.rstrip('/')}/api/tags", timeout=2).raise_for_status()
            llm_status = f"connected ({settings.llm_model})"
        except Exception:
            llm_status = "on, but the AI service is not answering"
            problems.append(
                "AI assist is switched on but Ollama is not reachable at "
                f"{settings.llm_base_url}. The app still works without it."
            )

    backups = sorted(settings.backups_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        problems.append("No backup has been made yet. Use the button below to make one now.")

    failing = repo.failing_jobs(conn)
    for job in failing:
        problems.append(f"The scheduled job '{job['job_name']}' failed on its last run.")

    free = free_space_bytes(settings.data_dir)
    if free < 500 * 1024 * 1024:
        problems.append(f"Only {_human_bytes(free)} of disk space is left.")

    jobs = getattr(request.app.state, "jobs", None)
    return templates.TemplateResponse(
        request,
        "status.html",
        context(
            request, conn, "status",
            settings=settings,
            problems=problems,
            ocr_status=ocr_status,
            llm_status=llm_status,
            db_size=_human_bytes(settings.db_path.stat().st_size) if settings.db_path.exists() else "not created yet",
            backup_count=len(backups),
            newest_backup=backups[0].name if backups else "none",
            free_space=_human_bytes(free),
            offsite_status=(
                f"rclone → {settings.rclone_remote}:{settings.rclone_path}"
                if settings.rclone_remote else "not set up"
            ),
            next_runs=jobs.next_runs() if jobs else [],
            job_runs=repo.recent_job_runs(conn, limit=15),
        ),
    )


@router.post("/status/backup")
def backup_now(settings: Settings = Depends(get_settings)):
    result = run_backup(settings, include_uploads=True)
    if result.status != "ok":
        return redirect("/status", f"The backup failed: {result.error}", "error")
    return redirect(
        "/status",
        f"Backup written ({_human_bytes(result.size_bytes)}). Offsite copy: {result.offsite_status}.",
        "ok",
    )
