"""Unit tests for statistics period resolution."""

from datetime import datetime, timedelta, timezone

from djehuty.services.statistics import resolve_period

_NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_no_arguments_is_all_time():
    assert resolve_period() == (None, None)


def test_last_week():
    date_from, date_to = resolve_period(period="last_week", now=_NOW)
    assert date_to == _NOW
    assert date_from == _NOW - timedelta(days=7)


def test_last_month():
    date_from, date_to = resolve_period(period="last_month", now=_NOW)
    assert date_to == _NOW
    assert date_from == _NOW - timedelta(days=30)


def test_unknown_named_period_is_all_time():
    assert resolve_period(period="last_decade", now=_NOW) == (None, None)


def test_explicit_from_and_to():
    date_from, date_to = resolve_period(date_from="2026-01-01", date_to="2026-02-01")
    assert date_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert date_to == datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_only_from():
    date_from, date_to = resolve_period(date_from="2026-01-01")
    assert date_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert date_to is None


def test_malformed_date_is_ignored():
    assert resolve_period(date_from="not-a-date", date_to="2026-13-99") == (None, None)


def test_named_period_takes_precedence_over_dates():
    date_from, date_to = resolve_period(
        period="last_week", date_from="2020-01-01", date_to="2020-02-01", now=_NOW
    )
    assert date_from == _NOW - timedelta(days=7)
    assert date_to == _NOW
