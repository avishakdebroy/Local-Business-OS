"""Background jobs.

Every job records its outcome in ``job_runs`` and swallows its exceptions. A job
that raises into APScheduler leaves no trace the operator can see; a job that
writes a row leaves one the weekly report and the home screen both surface.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from lbos.db.connection import connect
from lbos.domain.periods import now_utc_iso
from lbos.ledger import repositories as repo
from lbos.ops.backup import run_backup
from lbos.reporting.weekly import run_weekly_report
from lbos.settings import Settings

log = logging.getLogger("lbos.jobs")


def record_job(settings: Settings, name: str, work: Callable[[Any], Any]) -> dict[str, Any]:
    """Run ``work`` with its own connection, recording success or failure."""
    started = now_utc_iso()
    conn = connect(settings.db_path)
    try:
        result = work(conn)
        detail = str(result)[:1000] if result is not None else None
        status = "ok"
    except Exception as exc:
        log.exception("job %s failed", name)
        detail = f"{type(exc).__name__}: {exc}"[:1000]
        status = "error"
        result = None
    finally:
        try:
            repo.insert_job_run(
                conn, job_name=name, status=status, detail=detail,
                started_at=started, finished_at=now_utc_iso(),
            )
            conn.commit()
        except Exception:  # pragma: no cover - the database itself is unavailable
            log.exception("could not record the outcome of job %s", name)
        conn.close()

    return {"job": name, "status": status, "detail": detail}


def weekly_report_job(settings: Settings) -> dict[str, Any]:
    return record_job(
        settings,
        "weekly_report",
        lambda conn: run_weekly_report(conn, settings)["delivery_status"],
    )


def nightly_backup_job(settings: Settings) -> dict[str, Any]:
    return record_job(
        settings,
        "nightly_backup",
        lambda conn: run_backup(settings, include_uploads=False).as_dict(),
    )


def weekly_full_backup_job(settings: Settings) -> dict[str, Any]:
    return record_job(
        settings,
        "weekly_full_backup",
        lambda conn: run_backup(settings, include_uploads=True).as_dict(),
    )


class Jobs:
    """Owns the scheduler so the application does not need a module-level global."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if self.scheduler is not None or not self.settings.scheduler_enabled:
            return

        scheduler = BackgroundScheduler(timezone=self.settings.timezone)
        settings = self.settings

        scheduler.add_job(
            lambda: weekly_report_job(settings),
            CronTrigger(
                day_of_week=settings.report_day,
                hour=settings.report_hour,
                minute=settings.report_minute,
            ),
            id="weekly_report",
            replace_existing=True,
            misfire_grace_time=6 * 3600,
        )
        scheduler.add_job(
            lambda: nightly_backup_job(settings),
            CronTrigger(hour=settings.backup_hour, minute=settings.backup_minute),
            id="nightly_backup",
            replace_existing=True,
            misfire_grace_time=6 * 3600,
        )
        scheduler.add_job(
            lambda: weekly_full_backup_job(settings),
            CronTrigger(
                day_of_week="fri",
                hour=settings.backup_hour,
                minute=settings.backup_minute + 30 if settings.backup_minute < 30 else 0,
            ),
            id="weekly_full_backup",
            replace_existing=True,
            misfire_grace_time=12 * 3600,
        )

        scheduler.start()
        self.scheduler = scheduler
        log.info("scheduler started (timezone %s)", settings.timezone)

    def stop(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None

    def next_runs(self) -> list[dict[str, str]]:
        if self.scheduler is None:
            return []
        return [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else "-",
            }
            for job in self.scheduler.get_jobs()
        ]
