"""Dates and reporting windows.

Two clocks exist in this system and mixing them is the classic way to lose
records:

* ``captured_at`` - when the app saw a document. Stored as UTC, used only for
  audit ordering.
* ``entry_date`` - the local business date the money or stock actually moved.
  Stored as a plain ``YYYY-MM-DD`` local date, and it is the *only* thing
  reports filter on.

Because reports compare local dates to local dates, no timezone offset can shift
a window and silently drop a day's takings.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lbos.domain.numerals import to_ascii_digits

ISO_DATE = "%Y-%m-%d"

_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b"), "dmy2"),
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})\s*[-/ ]?\s*([a-z]{3,9})\.?\s*[-/, ]?\s*(\d{2,4})\b", re.IGNORECASE
)


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    """UTC timestamp for audit columns, e.g. ``2026-09-02T04:17:56Z``."""
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_now(timezone_name: str) -> datetime:
    return datetime.now(tz(timezone_name))


def local_today(timezone_name: str) -> date:
    return local_now(timezone_name).date()


def iso(day: date) -> str:
    return day.strftime(ISO_DATE)


def parse_iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.strptime(str(text).strip()[:10], ISO_DATE).date()
    except ValueError:
        return None


def parse_date(text: str | None, today: date | None = None) -> date | None:
    """Find a calendar date in free text.

    Ambiguous numeric dates are read day-first (``05/09/2026`` is 5 September),
    which is the convention in Bangladesh. Dates are rejected if they fall more
    than a day in the future or more than five years back, since those are
    almost always an OCR misread of an amount or a phone number.
    """
    if not text:
        return None
    cleaned = to_ascii_digits(str(text))
    candidates: list[date] = []

    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(cleaned):
            a, b, c = (int(g) for g in match.groups())
            try:
                if order == "ymd":
                    candidates.append(date(a, b, c))
                elif order == "dmy":
                    candidates.append(date(c, b, a))
                else:
                    candidates.append(date(2000 + c, b, a))
            except ValueError:
                continue

    for match in _TEXT_DATE.finditer(cleaned):
        day_s, month_s, year_s = match.groups()
        month = _MONTHS.get(month_s[:3].lower())
        if not month:
            continue
        year = int(year_s)
        if year < 100:
            year += 2000
        try:
            candidates.append(date(year, month, int(day_s)))
        except ValueError:
            continue

    if not candidates:
        return None

    reference = today or date.today()
    plausible = [
        d for d in candidates
        if reference - timedelta(days=365 * 5) <= d <= reference + timedelta(days=1)
    ]
    return plausible[0] if plausible else None


def week_window(timezone_name: str, anchor: date | None = None, days: int = 7) -> tuple[date, date]:
    """Return the inclusive local date range a report covers.

    ``anchor`` is the last day included. With the default 7 days, a report run
    on a Sunday covers Monday through Sunday. Consecutive windows abut exactly:
    no day is counted twice and none is skipped.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    end = anchor or local_today(timezone_name)
    return end - timedelta(days=days - 1), end


def previous_window(start: date, days: int = 7) -> tuple[date, date]:
    """The window immediately before the one starting at ``start``."""
    end = start - timedelta(days=1)
    return end - timedelta(days=days - 1), end
