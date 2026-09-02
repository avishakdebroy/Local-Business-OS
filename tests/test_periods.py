"""Reporting windows must tile the calendar with no gaps and no overlaps."""

from datetime import date, timedelta

import pytest

from lbos.domain.periods import (
    local_today,
    now_utc_iso,
    parse_date,
    previous_window,
    week_window,
)


def test_a_week_window_is_seven_inclusive_days():
    start, end = week_window("Asia/Dhaka", anchor=date(2026, 8, 30))
    assert (start, end) == (date(2026, 8, 24), date(2026, 8, 30))
    assert (end - start).days + 1 == 7


def test_consecutive_windows_abut_exactly():
    """The bug this guards: a six-hour band lost between one week and the next."""
    _, previous_end = previous_window(date(2026, 8, 24))
    assert previous_end == date(2026, 8, 23)
    assert previous_end + timedelta(days=1) == date(2026, 8, 24)


def test_every_day_of_a_year_falls_in_exactly_one_weekly_window():
    anchor = date(2026, 12, 27)
    covered: list[date] = []
    for _ in range(52):
        start, end = week_window("Asia/Dhaka", anchor=anchor)
        day = start
        while day <= end:
            covered.append(day)
            day += timedelta(days=1)
        anchor = start - timedelta(days=1)

    assert len(covered) == len(set(covered)) == 52 * 7


def test_utc_timestamps_are_marked_as_utc():
    assert now_utc_iso().endswith("Z")


def test_local_today_uses_the_shop_timezone():
    assert isinstance(local_today("Asia/Dhaka"), date)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Date: 2026-08-30", date(2026, 8, 30)),
        ("তারিখ: ০৫/০৯/২০২৬", date(2026, 9, 5)),
        ("bill dated 12 Aug 2026", date(2026, 8, 12)),
        ("05/09/26", date(2026, 9, 5)),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, today=date(2026, 9, 10)) == expected


def test_ambiguous_dates_are_read_day_first():
    assert parse_date("05/09/2026", today=date(2026, 9, 30)) == date(2026, 9, 5)


def test_implausible_dates_are_rejected():
    assert parse_date("total 1250", today=date(2026, 9, 2)) is None
    assert parse_date("31/12/2099", today=date(2026, 9, 2)) is None
