"""Period parsing for statistics queries.

Turns the API period parameters into a (date_from, date_to) pair of aware
datetimes. Supported forms:

* ``period=last_week``  -> the last 7 days up to now
* ``period=last_month`` -> the last 30 days up to now
* ``date_from`` / ``date_to`` as YYYY-MM-DD (either or both)
* nothing -> (None, None), meaning all time

``now`` is injectable so callers and tests can pin the reference time.
"""

from datetime import datetime, timedelta, timezone

_NAMED_PERIODS = {
    "last_week": timedelta(days=7),
    "last_month": timedelta(days=30),
}

_DATE_FORMAT = "%Y-%m-%d"


def _parse_date(value):
    """Parse a YYYY-MM-DD string into an aware datetime, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def resolve_period(period=None, date_from=None, date_to=None, now=None):
    """Return (date_from, date_to) datetimes for the requested period.

    A named ``period`` takes precedence over explicit from/to. An unrecognised
    named period is treated as all time.
    """
    if period:
        delta = _NAMED_PERIODS.get(period)
        if delta is None:
            return (None, None)
        reference = now or datetime.now(timezone.utc)
        return (reference - delta, reference)

    return (_parse_date(date_from), _parse_date(date_to))
