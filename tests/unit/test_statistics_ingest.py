"""Unit tests for the usage statistics ingest path.

Covers the batched buffer (size-triggered flush, shutdown flush, timestamp
parsing, bounded drop, resilience to a failing database) and the routing of
SparqlInterface.insert_log_entry to the buffer when the SQL store is enabled.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select

from djehuty.services.statistics import (
    StatisticsService,
    UsageEventBuffer,
    log_events,
    upgrade_to_head,
)
from djehuty.services.statistics.buffer import _parse_timestamp


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'ingest.db'}"
    upgrade_to_head(url)
    return create_engine(url)


def _count(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(log_events)).scalar()


def test_parse_timestamp_valid():
    parsed = _parse_timestamp("2026-06-01T12:00:00Z")
    assert parsed == datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_timestamp_malformed_falls_back_to_now():
    parsed = _parse_timestamp("not-a-timestamp")
    assert parsed.tzinfo is timezone.utc


def test_flush_writes_pending_events(engine):
    buffer = UsageEventBuffer(engine, batch_size=1000)
    buffer.add("2026-06-01T12:00:00Z", "1.2.3.4", "uuid-a", "dataset", "view")
    buffer.add("2026-06-01T12:00:01Z", None, "uuid-a", "dataset", "download")
    assert buffer.pending_count == 2

    written = buffer.flush()
    assert written == 2
    assert buffer.pending_count == 0
    assert _count(engine) == 2


def test_batch_size_triggers_flush(engine):
    buffer = UsageEventBuffer(engine, batch_size=2)
    buffer.add("2026-06-01T12:00:00Z", None, "uuid-a", "dataset", "view")
    assert buffer.pending_count == 1
    # The second add reaches the batch size and flushes both.
    buffer.add("2026-06-01T12:00:01Z", None, "uuid-a", "dataset", "view")
    assert buffer.pending_count == 0
    assert _count(engine) == 2


def test_flush_on_empty_buffer_is_noop(engine):
    buffer = UsageEventBuffer(engine, batch_size=10)
    assert buffer.flush() == 0


def test_failing_database_drops_without_raising():
    # An engine pointed at an un-migrated database: the insert fails, and the
    # buffer must drop the events without propagating the error.
    engine = create_engine("sqlite:///:memory:")
    buffer = UsageEventBuffer(engine, batch_size=10)
    buffer.add("2026-06-01T12:00:00Z", None, "uuid-a", "dataset", "view")
    written = buffer.flush()
    assert written == 0
    assert buffer.dropped_count == 1
    assert buffer.pending_count == 0


def test_service_records_and_stop_flushes(tmp_path):
    url = f"sqlite:///{tmp_path / 'svc.db'}"
    service = StatisticsService(url, flush_interval=60, flush_batch_size=1000)
    service.migrate()
    service.record("2026-06-01T12:00:00Z", "1.2.3.4", "uuid-a", "dataset", "view")
    service.record("2026-06-01T12:00:01Z", None, "uuid-a", "dataset", "download")
    assert service.buffer.pending_count == 2

    service.stop()
    assert service.buffer.pending_count == 0
    assert _count(service.engine) == 2


def test_insert_log_entry_routes_to_buffer(tmp_path):
    from djehuty.web.database import SparqlInterface

    url = f"sqlite:///{tmp_path / 'route.db'}"
    service = StatisticsService(url, flush_batch_size=1000)
    service.migrate()

    db = SparqlInterface()
    db.statistics_service = service

    # db.sparql is None; if this hit the RDF path it would fail. It must buffer.
    assert db.insert_log_entry("2026-06-01T12:00:00Z", "9.9.9.9", "uuid-x", "dataset", "download")
    assert service.buffer.pending_count == 1

    service.stop()
    assert _count(service.engine) == 1


def test_insert_log_entry_rejects_non_string_event_type(tmp_path):
    from djehuty.web.database import SparqlInterface

    url = f"sqlite:///{tmp_path / 'reject.db'}"
    service = StatisticsService(url, flush_batch_size=1000)
    service.migrate()

    db = SparqlInterface()
    db.statistics_service = service

    assert db.insert_log_entry("2026-06-01T12:00:00Z", None, "uuid-x", "dataset", 123) is False
    assert service.buffer.pending_count == 0
