"""SQLAlchemy Core schema for the usage statistics store.

A single append-only table holds raw view and download events. Aggregation is
done at query time, so there is no rollup table. The metadata object here is the
single source of truth for the schema and is referenced by both the query layer
and the Alembic migrations.

See design-docs/usage-statistics-sql-store.md for the data model.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)

metadata = MetaData()

# BigInteger on Postgres (production), plain Integer on SQLite so the primary key
# maps to the auto-incrementing rowid; a BIGINT primary key does not autoincrement
# on SQLite.
_id_type = BigInteger().with_variant(Integer, "sqlite")

# Raw usage events, one row per view or download. item_uuid is the container
# UUID of the dataset or collection. event_type is one of the values recorded
# today: view, privateView, download, reviewerDownload, gitDownload.
log_events = Table(
    "log_events",
    metadata,
    Column("id", _id_type, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("ip_address", String(64), nullable=True),
    Column("item_uuid", String(36), nullable=False),
    Column("item_type", String(16), nullable=False),
    Column("event_type", String(32), nullable=False),
    # Per-item period queries: counts and timelines for a single dataset.
    Index("ix_log_events_item", "item_uuid", "event_type", "created_at"),
    # Site-wide period queries and rankings across all items.
    Index("ix_log_events_created_at", "created_at"),
)
