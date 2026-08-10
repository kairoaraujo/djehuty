"""Unit tests for the SQL read-side of the usage statistics store.

Exercises the count primitives (per-item totals, ranked counts, and the
per-month timeline) with and without a period filter, against SQLite.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine

from djehuty.services.statistics import StatisticsStore, log_events, upgrade_to_head


def _dt(year, month, day):
    return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.db'}"
    upgrade_to_head(url)
    engine = create_engine(url)
    events = [
        # dataset A: 3 downloads (May, Jun, Jun), 1 view
        {"created_at": _dt(2026, 5, 10), "ip_address": None, "item_uuid": "A",
         "item_type": "dataset", "event_type": "download"},
        {"created_at": _dt(2026, 6, 1), "ip_address": None, "item_uuid": "A",
         "item_type": "dataset", "event_type": "download"},
        {"created_at": _dt(2026, 6, 2), "ip_address": None, "item_uuid": "A",
         "item_type": "dataset", "event_type": "download"},
        {"created_at": _dt(2026, 6, 2), "ip_address": None, "item_uuid": "A",
         "item_type": "dataset", "event_type": "view"},
        # dataset B: 1 download
        {"created_at": _dt(2026, 6, 3), "ip_address": None, "item_uuid": "B",
         "item_type": "dataset", "event_type": "download"},
    ]
    with engine.begin() as conn:
        conn.execute(log_events.insert(), events)
    return StatisticsStore(engine)


def test_count_for_item_all_time(store):
    assert store.count_for_item("A", "download") == 3
    assert store.count_for_item("A", "view") == 1
    assert store.count_for_item("B", "download") == 1
    assert store.count_for_item("missing", "download") == 0


def test_count_for_item_with_period(store):
    june = store.count_for_item("A", "download", date_from=_dt(2026, 6, 1))
    assert june == 2
    may_only = store.count_for_item(
        "A", "download", date_from=_dt(2026, 5, 1), date_to=_dt(2026, 6, 1)
    )
    assert may_only == 1


def test_counts_by_item_ranked(store):
    ranked = store.counts_by_item("download")
    assert ranked == [("A", 3), ("B", 1)]


def test_counts_by_item_paging(store):
    top1 = store.counts_by_item("download", limit=1)
    assert top1 == [("A", 3)]
    second = store.counts_by_item("download", limit=1, offset=1)
    assert second == [("B", 1)]


def test_counts_by_item_with_period(store):
    ranked = store.counts_by_item("download", date_from=_dt(2026, 6, 1))
    assert ranked == [("A", 2), ("B", 1)]


def test_timeline_for_item(store):
    timeline = store.timeline_for_item("A", "download")
    assert timeline == [("A", "2026-05", 1), ("A", "2026-06", 2)]


def test_timeline_for_item_with_period(store):
    timeline = store.timeline_for_item("A", "download", date_from=_dt(2026, 6, 1))
    assert timeline == [("A", "2026-06", 2)]
