"""Unit tests for the usage statistics schema and migration.

Runs the Alembic migration against a throwaway SQLite database and checks that
the log_events table, its columns and indexes are created, that a downgrade
removes it, and that an insert/select round trip works.
"""

from datetime import datetime, timezone

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select

from djehuty.services.statistics import log_events, upgrade_to_head
from djehuty.services.statistics.migrate import _alembic_config


@pytest.fixture
def sqlite_url(tmp_path):
    return f"sqlite:///{tmp_path / 'stats.db'}"


def test_upgrade_creates_schema(sqlite_url):
    upgrade_to_head(sqlite_url)
    insp = inspect(create_engine(sqlite_url))

    assert "log_events" in insp.get_table_names()

    columns = {c["name"] for c in insp.get_columns("log_events")}
    assert columns == {
        "id",
        "created_at",
        "ip_address",
        "item_uuid",
        "item_type",
        "event_type",
    }

    indexes = {i["name"] for i in insp.get_indexes("log_events")}
    assert "ix_log_events_item" in indexes
    assert "ix_log_events_created_at" in indexes


def test_version_table_is_scoped(sqlite_url):
    upgrade_to_head(sqlite_url)
    insp = inspect(create_engine(sqlite_url))
    assert "djehuty_statistics_alembic_version" in insp.get_table_names()


def test_downgrade_removes_table(sqlite_url):
    upgrade_to_head(sqlite_url)
    command.downgrade(_alembic_config(sqlite_url), "base")

    insp = inspect(create_engine(sqlite_url))
    assert "log_events" not in insp.get_table_names()


def test_insert_and_select_round_trip(sqlite_url):
    upgrade_to_head(sqlite_url)
    engine = create_engine(sqlite_url)

    created = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            log_events.insert(),
            [
                {
                    "created_at": created,
                    "ip_address": "203.0.113.7",
                    "item_uuid": "27e6a01d-3f09-4d90-ae02-1d749ae9efb8",
                    "item_type": "dataset",
                    "event_type": "download",
                },
                {
                    "created_at": created,
                    "ip_address": None,
                    "item_uuid": "27e6a01d-3f09-4d90-ae02-1d749ae9efb8",
                    "item_type": "dataset",
                    "event_type": "view",
                },
            ],
        )

    with engine.connect() as conn:
        rows = conn.execute(
            select(log_events.c.event_type).where(
                log_events.c.item_uuid == "27e6a01d-3f09-4d90-ae02-1d749ae9efb8"
            )
        ).fetchall()

    assert sorted(r[0] for r in rows) == ["download", "view"]
