"""Read-side queries over the SQL usage statistics store.

These are the count primitives used to serve statistics: per-item totals, a
per-item timeline, and a site-wide "top items" ranking. All accept an optional
period (a from/to datetime range), computed at query time over the raw
``log_events`` table; there is no rollup table.

The results are keyed by container UUID. Dataset metadata (title, dataset_id,
figshare_url) lives in the RDF store, not here, so callers that need it enrich
these counts with a metadata lookup.
"""

from sqlalchemy import func, select

from djehuty.services.statistics.schema import log_events


def _month_expression(dialect_name):
    """A "YYYY-MM" month bucket expression portable across SQLite and Postgres."""
    if dialect_name == "postgresql":
        return func.to_char(log_events.c.created_at, "YYYY-MM")
    # SQLite and the default path.
    return func.strftime("%Y-%m", log_events.c.created_at)


def _apply_period(query, date_from, date_to):
    """Add created_at range filters to QUERY when bounds are given."""
    if date_from is not None:
        query = query.where(log_events.c.created_at >= date_from)
    if date_to is not None:
        query = query.where(log_events.c.created_at < date_to)
    return query


class StatisticsStore:
    """SQL-backed reader for usage statistics."""

    def __init__(self, engine):
        self._engine = engine

    def count_for_item(self, item_uuid, event_type, date_from=None, date_to=None):
        """Total count of EVENT_TYPE for one item, optionally within a period."""
        query = (
            select(func.count())
            .select_from(log_events)
            .where(
                log_events.c.item_uuid == item_uuid,
                log_events.c.event_type == event_type,
            )
        )
        query = _apply_period(query, date_from, date_to)
        with self._engine.connect() as conn:
            return int(conn.execute(query).scalar() or 0)

    def counts_by_item(self, event_type, date_from=None, date_to=None, limit=None, offset=None):
        """Ranked (item_uuid, count) pairs for EVENT_TYPE, highest first.

        Optionally restricted to a period and paged with LIMIT/OFFSET.
        """
        count_col = func.count().label("count")
        query = (
            select(log_events.c.item_uuid, count_col)
            .where(log_events.c.event_type == event_type)
            .group_by(log_events.c.item_uuid)
            .order_by(count_col.desc(), log_events.c.item_uuid)
        )
        query = _apply_period(query, date_from, date_to)
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
        with self._engine.connect() as conn:
            return [(row[0], int(row[1])) for row in conn.execute(query)]

    def timeline_for_item(self, item_uuid, event_type, date_from=None, date_to=None):
        """Per-month (item_uuid, "YYYY-MM", count) rows for one item.

        Months are formatted as YYYY-MM to match the existing timeline output.
        """
        month = _month_expression(self._engine.dialect.name).label("month")
        count_col = func.count().label("count")
        query = (
            select(month, count_col)
            .where(
                log_events.c.item_uuid == item_uuid,
                log_events.c.event_type == event_type,
            )
            .group_by(month)
            .order_by(month)
        )
        query = _apply_period(query, date_from, date_to)
        with self._engine.connect() as conn:
            return [(item_uuid, row[0], int(row[1])) for row in conn.execute(query)]
