"""API-level tests for the v3 statistics endpoints.

Drives the router through a TestClient with a fake database, checking that the
period parameters reach the database layer and that the per-dataset count
endpoint returns the expected shape.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from djehuty.application import create_app

_DATASET_UUID = "27e6a01d-3f09-4d90-ae02-1d749ae9efb8"


class _StatsDB:
    """Records statistics calls and returns canned data."""

    def __init__(self):
        self.calls = []

    def dataset_statistics(self, **kwargs):
        self.calls.append(("dataset_statistics", kwargs))
        return [{"container_uuid": _DATASET_UUID, "dataset_id": 1,
                 "title": "T", "figshare_url": "u", "downloads": 5}]

    def dataset_statistics_timeline(self, **kwargs):
        self.calls.append(("dataset_statistics_timeline", kwargs))
        return [{"dataset_id": 1, "date": "2026-06", "downloads": 5}]

    def container_uuid_by_id(self, identifier, item_type="dataset"):
        return _DATASET_UUID

    def item_statistics(self, container_uuid, item_type="dataset",
                        date_from=None, date_to=None):
        self.calls.append(("item_statistics", (container_uuid, date_from, date_to)))
        return {"views": 12, "downloads": 5}


def _last(db, name):
    return next(c for c in reversed(db.calls) if c[0] == name)


def test_top_passes_period_to_db():
    db = _StatsDB()
    client = TestClient(create_app(db))
    resp = client.get("/v3/datasets/top/downloads?period=last_week")
    assert resp.status_code == 200
    _, kwargs = _last(db, "dataset_statistics")
    assert kwargs["date_from"] is not None
    assert kwargs["date_to"] is not None


def test_timeline_passes_explicit_dates_to_db():
    db = _StatsDB()
    client = TestClient(create_app(db))
    resp = client.get("/v3/datasets/timeline/downloads?id=1&from=2026-01-01&to=2026-02-01")
    assert resp.status_code == 200
    _, kwargs = _last(db, "dataset_statistics_timeline")
    assert kwargs["date_from"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert kwargs["date_to"] == datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_top_all_time_when_no_period():
    db = _StatsDB()
    client = TestClient(create_app(db))
    resp = client.get("/v3/datasets/top/downloads")
    assert resp.status_code == 200
    _, kwargs = _last(db, "dataset_statistics")
    assert kwargs["date_from"] is None
    assert kwargs["date_to"] is None


def test_dataset_count_endpoint():
    db = _StatsDB()
    client = TestClient(create_app(db))
    resp = client.get(f"/v3/datasets/{_DATASET_UUID}/statistics")
    assert resp.status_code == 200
    assert resp.json() == {
        "container_uuid": _DATASET_UUID,
        "views": 12,
        "downloads": 5,
    }


def test_dataset_count_endpoint_with_period():
    db = _StatsDB()
    client = TestClient(create_app(db))
    resp = client.get(f"/v3/datasets/{_DATASET_UUID}/statistics?period=last_month")
    assert resp.status_code == 200
    _, args = _last(db, "item_statistics")
    _uuid, date_from, date_to = args
    assert date_from is not None and date_to is not None
