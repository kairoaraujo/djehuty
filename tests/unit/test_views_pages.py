"""Unit tests for the first public UI pages (djehuty.views.router).

Pins the faithful behaviour of the legacy ui_home / ui_redirect_to_home /
robots_txt / sitemap / colors_css / loader_svg handlers: content negotiation,
the portal redirect, and the rendered media types.
"""

import pytest
from fastapi.testclient import TestClient

from djehuty.web.config import config
from djehuty.application import create_app


VALID_UUID = "12345678-1234-1234-8234-123456789abc"


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

    def collections(self, **kwargs):
        return []

    def root_categories(self):
        return [{"id": 1, "uuid": "c1", "title": "Cat"}]

    def category_by_id(self, category_id):
        return {"id": 1, "uuid": "c1", "title": "Cat"}

    def subcategories_for_category(self, uuid):
        return []

    def group_by_name(self, name, startswith=False):
        return [] if startswith else {"group_id": 1, "name": name}

    def categories(self, **kwargs):
        return []

    def licenses(self):
        return []

    def group(self, **kwargs):
        return []

    def author_profile(self, uri):
        return [{"full_name": "Ada", "group_id": 28586, "account": "account:a1"}]

    def author_public_items(self, uri):
        return []

    def associated_authors(self, uri):
        return []

    def account_categories(self, account_uuid):
        return []

    def feedback_reviewer_email_addresses(self):
        return ["reviewer@example.org"]

    def opendap_to_doi(self, **kwargs):
        return []

    def __getattr__(self, name):
        if name.startswith("may_"):
            return lambda *a, **k: False
        raise AttributeError(name)


@pytest.fixture
def client():
    return TestClient(create_app(FakeDB()), follow_redirects=False)


def _client(db):
    return TestClient(create_app(db), follow_redirects=False)


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


# --- second public-pages batch ----------------------------------------------

def test_browse_redirects_for_browsers(client):
    resp = client.get("/browse", headers={"Accept": "text/html"})
    assert resp.status_code == 301
    assert resp.headers["location"] == "/"


def test_category_overview_renders(client):
    resp = client.get("/category", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "<html" in resp.text


def test_category_requires_html(client):
    assert client.get("/category", headers={"Accept": "application/json"}).status_code == 406


def test_categories_detail_renders(client):
    resp = client.get("/categories/1", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_categories_invalid_id_is_404(client):
    resp = client.get("/categories/not-an-int", headers={"Accept": "text/html"})
    assert resp.status_code == 404


def test_categories_missing_category_is_404():
    class DB(FakeDB):
        def category_by_id(self, category_id):
            return None
    resp = _client(DB()).get("/categories/9", headers={"Accept": "text/html"})
    assert resp.status_code == 404


def test_institution_renders(client):
    resp = client.get("/institutions/Delft_University", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_author_valid_uuid_renders(client):
    resp = client.get(f"/authors/{VALID_UUID}", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_author_invalid_uuid_is_403(client):
    resp = client.get("/authors/not-a-uuid", headers={"Accept": "text/html"})
    assert resp.status_code == 403


def test_author_missing_profile_is_404():
    class DB(FakeDB):
        def author_profile(self, uri):
            return []
    resp = _client(DB()).get(f"/authors/{VALID_UUID}", headers={"Accept": "text/html"})
    assert resp.status_code == 404


def test_search_renders(client):
    resp = client.get("/search?search=water", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_opendap_renders(client):
    resp = client.get("/opendap_to_doi", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_opendap_single_doi_redirects():
    class DB(FakeDB):
        def opendap_to_doi(self, **kwargs):
            return [{"doi": "10.1234/abc", "title": "T"}]
    resp = _client(DB()).get("/opendap_to_doi", headers={"Accept": "text/html"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://doi.org/10.1234/abc"


def test_feedback_get_renders(client):
    resp = client.get("/feedback", headers={"Accept": "text/html"})
    assert resp.status_code == 200


def test_feedback_404_when_no_reviewers():
    class DB(FakeDB):
        def feedback_reviewer_email_addresses(self):
            return []
    resp = _client(DB()).get("/feedback", headers={"Accept": "text/html"})
    assert resp.status_code == 404


def test_feedback_post_success_renders_page(client):
    resp = client.post("/feedback", headers={"Accept": "text/html"},
                       data={"email": "a@b.org", "feedback_type": "bug",
                             "description": "Something is broken here."})
    assert resp.status_code == 200
    assert "Thank you" in resp.text


def test_data_access_request_requires_json(client):
    resp = client.post("/data_access_request", headers={"Accept": "text/html"}, json={})
    assert resp.status_code == 406


def test_data_access_request_missing_dataset_is_400(client):
    resp = client.post("/data_access_request", headers={"Accept": "application/json"},
                       json={"email": "a@b.org", "name": "A", "dataset_id": "d1",
                             "version": "1", "reason": "a sufficiently long reason"})
    assert resp.status_code == 400


def test_data_access_request_confidential_succeeds():
    class DB(FakeDB):
        def datasets(self, **kwargs):
            return [{"title": "T", "is_confidential": True, "doi": "10.1/x"}]
        def contact_info_from_container(self, dataset_id):
            return None
        def reviewer_email_addresses(self):
            return ["rev@example.org"]
    resp = _client(DB()).post("/data_access_request", headers={"Accept": "application/json"},
                              json={"email": "a@b.org", "name": "A", "dataset_id": "d1",
                                    "version": "1", "reason": "a sufficiently long reason"})
    assert resp.status_code == 204
