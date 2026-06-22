"""Unit tests for the first public UI pages (djehuty.views.router).

Pins the faithful behaviour of the legacy ui_home / ui_redirect_to_home /
robots_txt / sitemap / colors_css / loader_svg handlers: content negotiation,
the portal redirect, and the rendered media types.
"""

import pytest
from fastapi.testclient import TestClient

from djehuty.web.config import config
from djehuty.application import create_app


class FakeDB:
    def account_by_session_token(self, token):
        return None

    def is_depositor(self, token, account=None):
        return False

    def repository_statistics(self):
        return {"datasets": 10, "authors": 5, "collections": 2, "files": 7, "bytes": 1234}

    def latest_datasets_portal(self, page_size):
        return []

    def datasets(self, **kwargs):
        return []

    def __getattr__(self, name):
        if name.startswith("may_"):
            return lambda *a, **k: False
        raise AttributeError(name)


@pytest.fixture
def client():
    return TestClient(create_app(FakeDB()), follow_redirects=False)


def test_home_renders_html(client):
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text
    # The Server header carries the site name, faithful to legacy response().
    assert resp.headers.get("server") == config.site_name


def test_home_requires_html(client):
    resp = client.get("/", headers={"Accept": "application/json"})
    assert resp.status_code == 406


def test_portal_redirects_for_browsers(client):
    resp = client.get("/portal", headers={"Accept": "text/html"})
    assert resp.status_code == 301
    assert resp.headers["location"] == "/"


def test_portal_json_for_non_browsers(client):
    resp = client.get("/portal", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "OK"}


def test_robots_allow_when_crawlers_enabled(client, monkeypatch):
    monkeypatch.setattr(config, "allow_crawlers", True, raising=False)
    monkeypatch.setattr(config, "base_url", "https://data.example.org", raising=False)
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Allow: /" in resp.text
    assert "Sitemap: https://data.example.org/sitemap.xml" in resp.text


def test_robots_disallow_when_crawlers_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "allow_crawlers", False, raising=False)
    resp = client.get("/robots.txt")
    assert "Disallow: /" in resp.text


def test_sitemap_renders_xml(client):
    resp = client.get("/sitemap.xml", headers={"Accept": "application/xml"})
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]


def test_sitemap_requires_xml(client):
    resp = client.get("/sitemap.xml", headers={"Accept": "text/html"})
    assert resp.status_code == 406


def test_colors_css_renders(client):
    resp = client.get("/theme/colors.css", headers={"Accept": "text/css"})
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_loader_svg_renders(client):
    resp = client.get("/theme/loader.svg", headers={"Accept": "image/svg+xml"})
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
