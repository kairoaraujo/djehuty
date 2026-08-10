"""In-process batched buffer for usage events.

Every djehuty process buffers view and download events in memory and flushes
them to the shared statistics database in batches, so that a high-traffic
deployment does not issue one INSERT per request. Many processes writing batched
inserts to one shared database is the multi-pod-safe ingest primitive.

The buffer is bounded: if the database is unreachable or the buffer is full,
events are dropped with a warning rather than growing memory without limit.
Losing some usage events is acceptable; taking down a worker is not.
"""

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.engine import Engine

from djehuty.services.statistics.schema import log_events

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Hard cap on buffered events so a database outage cannot exhaust memory. Well
# above a normal flush batch; when exceeded, new events are dropped.
_MAX_BUFFERED = 100_000


def _parse_timestamp(value):
    """Parse the caller's "%Y-%m-%dT%H:%M:%SZ" timestamp into an aware datetime.

    Falls back to the current time when the value is missing or malformed, so a
    bad timestamp never loses the event.
    """
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


class UsageEventBuffer:
    """Thread-safe buffer that flushes usage events to the database in batches."""

    def __init__(self, engine: Engine, batch_size: int = 1000, logger=None):
        self._engine = engine
        self._batch_size = max(1, int(batch_size))
        self._log = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._events = []
        self._dropped = 0

    def add(self, created_date, ip_address, item_uuid, item_type, event_type):
        """Append one event; flush when the batch size is reached."""
        event = {
            "created_at": _parse_timestamp(created_date),
            "ip_address": ip_address,
            "item_uuid": item_uuid,
            "item_type": item_type,
            "event_type": event_type,
        }
        should_flush = False
        with self._lock:
            if len(self._events) >= _MAX_BUFFERED:
                self._dropped += 1
                if self._dropped % 1000 == 1:
                    self._log.warning(
                        "Usage-statistics buffer full; dropped %d events so far.",
                        self._dropped,
                    )
                return False
            self._events.append(event)
            should_flush = len(self._events) >= self._batch_size

        if should_flush:
            self.flush()
        return True

    def flush(self):
        """Write the buffered events to the database in one batch.

        Events are taken under the lock, then written outside it so request
        threads are not blocked on the database. On failure the events are
        dropped and counted; they are not requeued, to keep the buffer bounded.
        """
        with self._lock:
            if not self._events:
                return 0
            pending = self._events
            self._events = []

        try:
            with self._engine.begin() as connection:
                connection.execute(log_events.insert(), pending)
            return len(pending)
        except Exception as error:  # noqa: BLE001 - never let flushing crash a request
            self._dropped += len(pending)
            self._log.warning(
                "Failed to flush %d usage events (%s); dropped (total dropped: %d).",
                len(pending),
                error,
                self._dropped,
            )
            return 0

    @property
    def pending_count(self):
        """Number of events currently buffered."""
        with self._lock:
            return len(self._events)

    @property
    def dropped_count(self):
        """Number of events dropped since start."""
        return self._dropped
