"""Reports must count every entry exactly once, on its business date."""

from datetime import date, datetime, timedelta, timezone

from lbos.domain.periods import iso, previous_window, week_window
from lbos.ledger import repositories as repo
from lbos.reporting.weekly import build_summary, render_text, run_weekly_report


def add_entry(conn, entry_date: str, direction: str, paisa: int, captured_at: str | None = None):
    """Insert a posted entry, controlling the business date and the capture instant separately."""
    document_id = repo.insert_document(
        conn,
        content_hash=f"{entry_date}-{direction}-{paisa}-{captured_at}",
        source_kind="text", doc_type=direction, status="posted", confidence=1.0,
        raw_text="x", extraction={}, extractor="test",
    )
    if captured_at:
        conn.execute("UPDATE documents SET captured_at = ? WHERE id = ?", (captured_at, document_id))
    repo.insert_money_entry(
        conn, document_id=document_id, entry_date=entry_date,
        direction=direction, total_paisa=paisa,
    )
    conn.commit()
    return document_id


def test_entries_are_counted_on_their_business_date_not_their_capture_time(conn):
    """A Saturday sale typed in on Monday belongs to Saturday's week."""
    add_entry(conn, "2026-08-29", "sale", 50_000, captured_at="2026-08-31T04:00:00Z")
    week = repo.money_totals(conn, "2026-08-24", "2026-08-30")
    assert week["sale_paisa"] == 50_000


def test_no_entry_is_lost_between_consecutive_weeks(conn):
    """The defect this guards against dropped a six-hour band every week.

    Entries are captured at Dhaka evening times, whose UTC instants fall on the
    previous day. Filtering on the business date makes that irrelevant.
    """
    dhaka_evening_utc = "2026-08-23T15:30:00Z"  # 21:30 local on 23 Aug
    for day in range(24, 31):
        add_entry(conn, f"2026-08-{day}", "sale", 10_000, captured_at=dhaka_evening_utc)
    add_entry(conn, "2026-08-23", "sale", 77_000, captured_at=dhaka_evening_utc)

    this_week = repo.money_totals(conn, "2026-08-24", "2026-08-30")
    previous_start, previous_end = previous_window(date(2026, 8, 24))
    last_week = repo.money_totals(conn, iso(previous_start), iso(previous_end))

    assert this_week["sale_paisa"] == 70_000
    assert last_week["sale_paisa"] == 77_000

    total_recorded = conn.execute("SELECT SUM(total_paisa) FROM money_entries").fetchone()[0]
    assert this_week["sale_paisa"] + last_week["sale_paisa"] == total_recorded


def test_boundary_days_belong_to_exactly_one_week(conn):
    add_entry(conn, "2026-08-23", "sale", 1_000)  # last day of the earlier week
    add_entry(conn, "2026-08-24", "sale", 2_000)  # first day of this week
    add_entry(conn, "2026-08-30", "sale", 4_000)  # last day of this week
    add_entry(conn, "2026-08-31", "sale", 8_000)  # first day of the next week

    assert repo.money_totals(conn, "2026-08-24", "2026-08-30")["sale_paisa"] == 6_000
    assert repo.money_totals(conn, "2026-08-17", "2026-08-23")["sale_paisa"] == 1_000
    assert repo.money_totals(conn, "2026-08-31", "2026-09-06")["sale_paisa"] == 8_000


def test_voided_entries_leave_the_totals(conn):
    document_id = add_entry(conn, "2026-08-25", "sale", 30_000)
    repo.void_money_entries_for_document(conn, document_id, "mistake")
    conn.commit()
    assert repo.money_totals(conn, "2026-08-24", "2026-08-30")["sale_paisa"] == 0


def test_net_is_sales_minus_purchases(conn):
    add_entry(conn, "2026-08-25", "sale", 100_000)
    add_entry(conn, "2026-08-26", "purchase", 40_000)
    totals = repo.money_totals(conn, "2026-08-24", "2026-08-30")
    assert totals["net_paisa"] == 60_000


def test_summary_compares_with_the_previous_week(conn):
    add_entry(conn, "2026-08-18", "sale", 100_000)
    add_entry(conn, "2026-08-25", "sale", 150_000)
    start, end = week_window("Asia/Dhaka", anchor=date(2026, 8, 30))
    summary = build_summary(conn, start, end)
    assert summary["sale_paisa"] == 150_000
    assert summary["previous_sale_paisa"] == 100_000


def test_the_report_warns_about_entries_waiting_for_review(conn, settings):
    from lbos.ledger import posting

    posting.capture(conn, settings, text="Electricity bill 3400 taka", today=date(2026, 9, 2))
    result = run_weekly_report(conn, settings, anchor=date(2026, 9, 2))
    assert result["summary"]["pending_review_count"] == 1
    assert "waiting on the Review screen" in result["text"]


def test_a_report_is_recorded_even_when_email_is_not_configured(conn, settings):
    result = run_weekly_report(conn, settings, anchor=date(2026, 9, 2))
    assert result["delivery_status"] == "skipped"
    run = repo.latest_report_run(conn)
    assert run["period_end"] == "2026-09-02"
    assert run["delivery_status"] == "skipped"


def test_a_failing_mail_server_does_not_cost_the_report(conn, settings, monkeypatch):
    """Generation and delivery are separate; only the email should fail."""
    from lbos.reporting import weekly

    monkeypatch.setattr(
        weekly, "send_report", lambda *a, **k: ("failed", "ConnectionRefusedError")
    )
    result = run_weekly_report(conn, settings, anchor=date(2026, 9, 2))
    assert result["delivery_status"] == "failed"
    assert repo.latest_report_run(conn)["report_path"]
    assert result["text"]


def test_the_report_file_is_written(conn, settings):
    result = run_weekly_report(conn, settings, anchor=date(2026, 9, 2))
    from pathlib import Path

    assert Path(result["report_path"]).read_text(encoding="utf-8") == result["text"]


def test_the_report_flags_a_failing_background_job(conn, settings):
    repo.insert_job_run(
        conn, job_name="nightly_backup", status="error", detail="disk full",
        started_at="x", finished_at="y",
    )
    conn.commit()
    summary = build_summary(conn, date(2026, 8, 27), date(2026, 9, 2))
    assert summary["failing_jobs"] == ["nightly_backup"]
    assert "nightly_backup" in render_text(summary)
