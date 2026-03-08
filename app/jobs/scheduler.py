from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.reporting import run_weekly_report
from app.services.backup import run_backup

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler

    if _scheduler is not None or not settings.scheduler_enabled:
        return

    _scheduler = BackgroundScheduler(timezone=settings.app_timezone)

    _scheduler.add_job(
        run_weekly_report,
        trigger=CronTrigger(
            day_of_week=settings.report_day,
            hour=settings.report_hour,
            minute=settings.report_minute,
        ),
        id="weekly_report",
        replace_existing=True,
    )

    _scheduler.add_job(
        run_backup,
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_backup",
        replace_existing=True,
    )

    _scheduler.start()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
