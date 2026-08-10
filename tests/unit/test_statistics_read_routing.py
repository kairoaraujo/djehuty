"""Unit tests for routing SparqlInterface statistics reads to the SQL store.

Verifies that dataset_statistics and dataset_statistics_timeline serve from SQL
counts enriched with RDF metadata when the SQL store is enabled, and that they
fall back to the RDF path for cases the SQL path does not cover (group/category
filters, cross-dataset timelines).
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine

from djehuty.services.statistics import StatisticsService, log_events, upgrade_to_head
from djehuty.web.database import SparqlInterface


def _dt(year, month, day):
    return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 'read.db'}"
    upgrade_to_head(url)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            log_events.insert(),
            [
                {"created_at": _dt(2026, 5, 1), "ip_address": None, "item_uuid": "uuid-a",
                 "item_type": "dataset", "event_type": "download"},
                {"created_at": _dt(2026, 6, 1), "ip_address": None, "item_uuid": "uuid-a",
                 "item_type": "dataset", "event_type": "download"},
                {"created_at": _dt(2026, 6, 2), "ip_address": None, "item_uuid": "uuid-a",
                 "item_type": "dataset", "event_type": "view"},
                {"created_at": _dt(2026, 6, 2), "ip_address": None, "item_uuid": "uuid-b",
                 "item_type": "dataset", "event_type": "download"},
            ],
        )

    service = StatisticsService(url, flush_batch_size=1000)
    interface = SparqlInterface()
    interface.statistics_service = service
    return interface


def test_dataset_statistics_merges_sql_counts_with_metadata(db, monkeypatch):
    # Stand in for the RDF metadata lookup keyed by container UUID.
    metadata = {
        "uuid-a": {"container_uuid": "uuid-a", "dataset_id": 101,
                   "title": "Dataset A", "figshare_url": "https://x/a"},
        "uuid-b": {"container_uuid": "uuid-b", "dataset_id": 102,
                   "title": "Dataset B", "figshare_url": "https://x/b"},
    }
    monkeypatch.setattr(
        db, "_SparqlInterface__dataset_metadata_for_statistics",
        lambda container_uuids=None, group_ids=None, category_ids=None: {
            u: metadata[u] for u in (container_uuids or metadata) if u in metadata
        },
    )

    result = db.dataset_statistics(item_type="downloads", limit=10, offset=0)

    assert result == [
        {"container_uuid": "uuid-a", "dataset_id": 101, "title": "Dataset A",
         "figshare_url": "https://x/a", "downloads": 2},
        {"container_uuid": "uuid-b", "dataset_id": 102, "title": "Dataset B",
         "figshare_url": "https://x/b", "downloads": 1},
    ]


def test_dataset_statistics_skips_items_without_metadata(db, monkeypatch):
    # uuid-b has no metadata (e.g. unpublished); it must be dropped, not error.
    monkeypatch.setattr(
        db, "_SparqlInterface__dataset_metadata_for_statistics",
        lambda container_uuids=None, group_ids=None, category_ids=None: {
            "uuid-a": {"container_uuid": "uuid-a", "dataset_id": 101,
                       "title": "A", "figshare_url": "u"}
        },
    )
    result = db.dataset_statistics(item_type="downloads")
    assert [r["container_uuid"] for r in result] == ["uuid-a"]


def test_dataset_statistics_group_filter_uses_sql_path(db, monkeypatch):
    # With a group filter, matching containers come from the RDF metadata lookup,
    # then are ranked by their SQL counts. uuid-a has 2 downloads, uuid-b has 1.
    monkeypatch.setattr(
        db, "_SparqlInterface__dataset_metadata_for_statistics",
        lambda container_uuids=None, group_ids=None, category_ids=None: {
            "uuid-a": {"container_uuid": "uuid-a", "dataset_id": 101,
                       "title": "A", "figshare_url": "u"},
            "uuid-b": {"container_uuid": "uuid-b", "dataset_id": 102,
                       "title": "B", "figshare_url": "v"},
        },
    )
    result = db.dataset_statistics(item_type="downloads", group_ids=[1])
    assert [(r["container_uuid"], r["downloads"]) for r in result] == [
        ("uuid-a", 2),
        ("uuid-b", 1),
    ]


def test_timeline_from_sql_labels_with_dataset_id(db, monkeypatch):
    monkeypatch.setattr(db, "container_uuid_by_id", lambda ident, item_type="dataset": "uuid-a")
    result = db.dataset_statistics_timeline(dataset_id=101, item_type="downloads")
    assert result == [
        {"dataset_id": 101, "date": "2026-05", "downloads": 1},
        {"dataset_id": 101, "date": "2026-06", "downloads": 1},
    ]


def test_timeline_without_dataset_id_falls_back_to_rdf(db, monkeypatch):
    called = {}

    def fake_run_query(query, *args, **kwargs):
        called["ran"] = True
        return []

    monkeypatch.setattr(db, "_SparqlInterface__run_query", fake_run_query)
    monkeypatch.setattr(db, "_SparqlInterface__query_from_template", lambda *a, **k: "QUERY")
    db.dataset_statistics_timeline(dataset_id=None, item_type="downloads")
    assert called.get("ran") is True


def test_item_statistics_returns_view_and_download_counts(db):
    counts = db.item_statistics("uuid-a", "dataset")
    assert counts == {"views": 1, "downloads": 2}


def test_item_statistics_with_period(db):
    counts = db.item_statistics("uuid-a", "dataset", date_from=_dt(2026, 6, 1))
    assert counts == {"views": 1, "downloads": 1}


def test_item_statistics_none_when_sql_disabled():
    plain = SparqlInterface()
    assert plain.item_statistics("uuid-a", "dataset") is None


def test_container_overlays_sql_counts(db, monkeypatch):
    # container() reads metadata from the RDF store; the totals are then
    # overlaid from the SQL store.
    monkeypatch.setattr(
        db, "_SparqlInterface__run_query",
        lambda *a, **k: [{"container_uuid": "uuid-a", "total_views": 999,
                          "total_downloads": 999}],
    )
    monkeypatch.setattr(db, "_SparqlInterface__query_from_template", lambda *a, **k: "QUERY")
    record = db.container("uuid-a", "dataset")
    assert record["total_views"] == 1
    assert record["total_downloads"] == 2


def test_timeline_with_period(db, monkeypatch):
    monkeypatch.setattr(db, "container_uuid_by_id", lambda ident, item_type="dataset": "uuid-a")
    result = db.dataset_statistics_timeline(
        dataset_id=101, item_type="downloads", date_from=_dt(2026, 6, 1)
    )
    assert result == [{"dataset_id": 101, "date": "2026-06", "downloads": 1}]
