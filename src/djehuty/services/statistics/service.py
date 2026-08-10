"""Usage statistics service: owns the engine, the ingest buffer, and its
periodic flush.

This is the object attached as ``app.state.statistics`` and shared with the
database interface so both the v3 API and the legacy web UI record events
through it. It is created only when the SQL store is enabled.
"""

import atexit
import logging
import threading

from djehuty.services.statistics.buffer import UsageEventBuffer
from djehuty.services.statistics.engine import create_statistics_engine
from djehuty.services.statistics.migrate import upgrade_to_head


class StatisticsService:
    """Ingest side of the SQL usage statistics store."""

    def __init__(self, database_url, flush_interval=5, flush_batch_size=1000, logger=None):
        self._log = logger or logging.getLogger(__name__)
        self._engine = create_statistics_engine(database_url)
        self._buffer = UsageEventBuffer(self._engine, flush_batch_size, self._log)
        self._flush_interval = max(1, int(flush_interval))
        self._stop = threading.Event()
        self._timer = None

    @property
    def engine(self):
        """The SQLAlchemy engine for the statistics database."""
        return self._engine

    @property
    def buffer(self):
        """The ingest buffer."""
        return self._buffer

    def migrate(self):
        """Bring the statistics schema up to head."""
        upgrade_to_head(str(self._engine.url))

    def start(self):
        """Start the periodic flush loop and register a shutdown flush."""
        self._schedule()
        atexit.register(self.stop)

    def _schedule(self):
        if self._stop.is_set():
            return
        self._timer = threading.Timer(self._flush_interval, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        try:
            self._buffer.flush()
        finally:
            self._schedule()

    def record(self, created_date, ip_address, item_uuid, item_type, event_type):
        """Buffer a usage event for later batched insertion."""
        return self._buffer.add(created_date, ip_address, item_uuid, item_type, event_type)

    def stop(self):
        """Stop the flush loop and flush any remaining events."""
        self._stop.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._buffer.flush()
