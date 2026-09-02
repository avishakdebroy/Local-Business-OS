"""The weekly report.

Every figure here is filtered on ``entry_date`` - the local business date the
money actually moved - not on when the app happened to see the document. That
is what keeps a receipt typed in on Monday for Saturday's sale in Saturday's
week, and what stops a timezone offset from quietly dropping a day's takings.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from lbos.domain.money import format_paisa
from lbos.domain.periods import iso, local_today, previous_window, week_window
from lbos.domain.quantity import format_milli
from lbos.ledger import repositories as repo
from lbos.reporting.delivery import send_report
from lbos.settings import Settings

PERIOD_DAYS = 7


def build_summary(
    conn: sqlite3.Connection, start: date, end: date
) -> dict[str, Any]:
    """Everything the report needs, as plain data."""
    start_iso, end_iso = iso(start), iso(end)
    totals = repo.money_totals(conn, start_iso, end_iso)

    previous_start, previous_end = previous_window(start, PERIOD_DAYS)
    previous = repo.money_totals(conn, iso(previous_start), iso(previous_end))

    low_stock = repo.stock_levels(conn, low_only=True)
    counts = repo.document_status_counts(conn)

    return {
        "period_start": start_iso,
        "period_end": end_iso,
        "previous_period_start": iso(previous_start),
        "previous_period_end": iso(previous_end),
        **totals,
        "previous_sale_paisa": previous["sale_paisa"],
        "previous_purchase_paisa": previous["purchase_paisa"],
        "previous_net_paisa": previous["net_paisa"],
        "purchase_categories": repo.category_breakdown(conn, start_iso, end_iso, "purchase"),
        "sale_payments": repo.payment_breakdown(conn, start_iso, end_iso),
        "low_stock": [
            {
                "name": row["name"],
                "on_hand": format_milli(row["on_hand_milli"], row["unit"]),
                "reorder_level": format_milli(row["reorder_level_milli"], row["unit"]),
            }
            for row in low_stock
        ],
        "low_stock_count": len(low_stock),
        "memo_count": len(repo.memos(conn, start_iso, end_iso)),
        "pending_review_count": counts.get("pending_review", 0),
        "failing_jobs": [row["job_name"] for row in repo.failing_jobs(conn)],
    }


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _change_line(label: str, current: int, previous: int) -> str:
    if previous == 0:
        suffix = "(no figure for the week before)" if current else ""
    else:
        change = (current - previous) / previous * 100
        suffix = f"({change:+.0f}% vs the week before)"
    return f"{label:<26} {format_paisa(current):>16}  {suffix}"


def render_text(summary: dict[str, Any]) -> str:
    """A plain-text report that reads well in an email and prints on any printer."""
    lines: list[str] = [
        "WEEKLY BUSINESS REPORT / সাপ্তাহিক হিসাব",
        f"{summary['period_start']} to {summary['period_end']}",
        "=" * 60,
        "",
        "MONEY / টাকা",
        "-" * 60,
        _change_line("Sales / বিক্রয়", summary["sale_paisa"], summary["previous_sale_paisa"]),
        f"{'  entries':<26} {summary['sale_count']:>16}",
        _change_line("Purchases / ক্রয়", summary["purchase_paisa"], summary["previous_purchase_paisa"]),
        f"{'  entries':<26} {summary['purchase_count']:>16}",
        "-" * 60,
        f"{'Net / নিট':<26} {format_paisa(summary['net_paisa']):>16}",
        "",
    ]

    if summary["purchase_categories"]:
        lines += ["WHERE THE MONEY WENT / খরচের খাত", "-" * 60]
        for row in summary["purchase_categories"]:
            lines.append(
                f"{row['category'][:24]:<26} {format_paisa(row['total_paisa']):>16}"
                f"  ({_plural(row['n'], 'entry', 'entries')})"
            )
        lines.append("")

    if summary["sale_payments"]:
        lines += ["HOW CUSTOMERS PAID / পরিশোধের ধরন", "-" * 60]
        for row in summary["sale_payments"]:
            lines.append(
                f"{row['method'][:24]:<26} {format_paisa(row['total_paisa']):>16}"
                f"  ({_plural(row['n'], 'entry', 'entries')})"
            )
        lines.append("")

    lines += ["LOW STOCK / কম মজুদ", "-" * 60]
    if summary["low_stock"]:
        for row in summary["low_stock"]:
            lines.append(f"  {row['name'][:34]:<36} {row['on_hand']:>12}  (reorder at {row['reorder_level']})")
    else:
        lines.append("  Nothing is below its reorder level.")
    lines.append("")

    if summary["pending_review_count"]:
        lines += [
            "NEEDS YOUR ATTENTION / আপনার দেখা দরকার",
            "-" * 60,
            f"  {_plural(summary['pending_review_count'], 'entry is', 'entries are')} "
            "waiting on the Review screen — not counted in the figures above.",
            "",
        ]

    if summary["failing_jobs"]:
        lines += [
            "WARNING / সতর্কতা",
            "-" * 60,
            "  These background jobs failed on their last run: "
            + ", ".join(summary["failing_jobs"]),
            "",
        ]

    lines.append(f"Notes recorded this week: {summary['memo_count']}")
    return "\n".join(lines)


def run_weekly_report(
    conn: sqlite3.Connection,
    settings: Settings,
    anchor: date | None = None,
) -> dict[str, Any]:
    """Generate, save, record and try to email the weekly report."""
    end = anchor or local_today(settings.timezone)
    start, end = week_window(settings.timezone, anchor=end, days=PERIOD_DAYS)

    summary = build_summary(conn, start, end)
    text = render_text(summary)

    settings.ensure_dirs()
    report_path: Path | None = settings.reports_dir / f"weekly-{iso(end)}.txt"
    try:
        report_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        summary["write_error"] = str(exc)
        report_path = None

    # The report is recorded before delivery is attempted, so a failing mail
    # server can never cost the shop the report itself.
    report_id = repo.insert_report_run(
        conn,
        period_start=iso(start),
        period_end=iso(end),
        report_path=str(report_path) if report_path else None,
        summary=summary,
        delivery_status="pending",
        delivery_detail=None,
    )
    conn.commit()

    status, detail = send_report(
        settings,
        subject=f"Weekly shop report - {iso(end)}",
        body=text,
        attachment=report_path,
    )
    repo.update_report_delivery(conn, report_id, status, detail)
    conn.commit()

    return {
        "report_id": report_id,
        "period_start": iso(start),
        "period_end": iso(end),
        "report_path": str(report_path) if report_path else None,
        "delivery_status": status,
        "delivery_detail": detail,
        "summary": summary,
        "text": text,
    }
