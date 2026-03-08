from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.db import get_conn


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.app_timezone))


def _week_window() -> tuple[datetime, datetime]:
    end = _now_local()
    start = end - timedelta(days=7)
    return start, end


def _send_email(subject: str, body: str, attachment_path: Path | None = None) -> str:
    if not (settings.smtp_host and settings.smtp_from and settings.report_email_to):
        return "skipped: smtp or recipient not configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = settings.report_email_to
    msg.set_content(body)

    if attachment_path and attachment_path.exists():
        data = attachment_path.read_bytes()
        msg.add_attachment(data, maintype="text", subtype="plain", filename=attachment_path.name)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)

    return "sent"


def run_weekly_report() -> dict:
    start, end = _week_window()
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    with get_conn() as conn:
        total_receipts = conn.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM receipts
            WHERE created_at >= ? AND created_at <= ?
            """,
            (start_iso, end_iso),
        ).fetchone()["total"]

        receipt_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM receipts
            WHERE created_at >= ? AND created_at <= ?
            """,
            (start_iso, end_iso),
        ).fetchone()["c"]

        low_stock = conn.execute(
            """
            SELECT name, current_qty, reorder_level
            FROM inventory_items
            WHERE current_qty <= reorder_level
            ORDER BY current_qty ASC
            LIMIT 50
            """
        ).fetchall()

        memo_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM memos
            WHERE created_at >= ? AND created_at <= ?
            """,
            (start_iso, end_iso),
        ).fetchone()["c"]

        lines = [
            f"Weekly Business Report ({start.date()} to {end.date()})",
            "",
            f"Receipts logged: {receipt_count}",
            f"Total receipt amount: {float(total_receipts):.2f}",
            f"Memos logged: {memo_count}",
            "",
            "Low Stock Items:",
        ]

        if low_stock:
            for row in low_stock:
                lines.append(f"- {row['name']}: {row['current_qty']} (reorder <= {row['reorder_level']})")
        else:
            lines.append("- None")

        report_text = "\n".join(lines)
        report_name = f"weekly-report-{end.strftime('%Y%m%d-%H%M%S')}.txt"
        report_path = settings.app_data_dir / "reports" / report_name
        report_path.write_text(report_text, encoding="utf-8")

        summary = {
            "receipt_count": int(receipt_count),
            "total_receipt_amount": float(total_receipts or 0),
            "memo_count": int(memo_count),
            "low_stock_count": len(low_stock),
        }

        email_status = _send_email(
            subject=f"Weekly shop report - {end.date()}",
            body=report_text,
            attachment_path=report_path,
        )

        conn.execute(
            """
            INSERT INTO report_runs (week_start, week_end, report_path, summary_json, email_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                start_iso,
                end_iso,
                str(report_path),
                json.dumps(summary),
                email_status,
                datetime.utcnow().isoformat(timespec="seconds") + "Z",
            ),
        )
        conn.commit()

    return {
        "status": "ok",
        "report_path": str(report_path),
        "email_status": email_status,
        "summary": summary,
    }
