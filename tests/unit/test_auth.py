"""Unit tests for the FastAPI auth surface (djehuty.auth) and its neutral
services (djehuty.services.{saml,orcid,content_negotiation}).

These pin the faithful AS-IS behaviour of the legacy ui_login / ui_logout /
saml_metadata handlers: success paths set the ``djehuty_session`` cookie and
redirect; the error paths return the legacy status codes.
"""

import pytest
from fastapi.testclient import TestClient

from djehuty.web.config import config
from djehuty.application import create_app
from djehuty.services import saml as saml_service
from djehuty.services import orcid as orcid_service
from djehuty.services import content_negotiation as cn


# --- neutral helpers --------------------------------------------------------

def test_content_negotiation_matches_legacy():
    # Missing Accept header == "*/*": accepted unless strict.
    assert cn.accepts_html(None) is True
    assert cn.accepts_html(None, strict=True) is False
    # Empty header is never acceptable.
    assert cn.accepts_html("") is False
    # Exact and wildcard.
    assert cn.accepts_html("text/html") is True
    assert cn.accepts_content_type("*/*", "text/html", strict=False) is True
    assert cn.accepts_content_type("*/*", "text/html", strict=True) is False
    assert cn.accepts_xml("application/xml") is True
    assert cn.accepts_xml("text/html") is False


def test_saml_request_to_saml_request(monkeypatch):
    monkeypatch.setattr(config, "base_url", "https://data.example.org", raising=False)
    fields = saml_service.request_to_saml_request("/saml/login", {"a": "b"}, {"c": "d"})
    assert fields == {
        "https": "on",
        "http_host": "data.example.org",
        "script_name": "/saml/login",
        "get_data": {"a": "b"},
        "post_data": {"c": "d"},
    }


def test_orcid_authorize_url(monkeypatch):
    monkeypatch.setattr(config, "orcid_endpoint", "https://orcid.org/oauth", raising=False)
    monkeypatch.setattr(config, "orcid_client_id", "APP-123", raising=False)
    monkeypatch.setattr(config, "base_url", "https://data.example.org", raising=False)
    url = orcid_service.authorize_url()
    assert url == ("https://orcid.org/oauth/authorize?client_id=APP-123"
                   "&response_type=code&scope=/authenticate"
                   "&redirect_uri=https://data.example.org/login")


# --- router flows -----------------------------------------------------------

class FakeDB:
    """Minimal db double recording the auth side effects under test."""
    def __init__(self, account=None, session=("tok", None, "sess-1")):
        self._account = account
        self._session = session
        self.deleted_sessions = []

    def account_by_email(self, email):
        return self._account

    def account_by_uuid(self, account_uuid):
        return self._account

    def insert_session(self, account_uuid, name=None):
        return self._session

    def delete_session(self, token):
        self.deleted_sessions.append(token)
        return True

    # Required by get_current_account when other routes are mounted, and by the
    # shared error-page renderer when a client asks for HTML.
    def account_by_session_token(self, token):
        return None

    def is_depositor(self, token, account=None):
        return False

    def __getattr__(self, name):
        if name.startswith("may_"):
            return lambda *a, **k: False
        raise AttributeError(name)


@pytest.fixture
def auth_config(monkeypatch):
    monkeypatch.setattr(config, "in_production", False, raising=False)
    monkeypatch.setattr(config, "automatic_login_email", None, raising=False)
    monkeypatch.setattr(config, "identity_provider", "saml", raising=False)
    monkeypatch.setattr(config, "base_url", "https://data.example.org", raising=False)
    return config


def _client(db, cookies=None):
    app = create_app(db)
    client = TestClient(app, follow_redirects=False)
    if cookies:
        client.cookies.update(cookies)
    return client


def test_login_automatic_sets_cookie_and_redirects_dashboard(auth_config, monkeypatch):
    monkeypatch.setattr(config, "automatic_login_email", "dev@example.org", raising=False)
    db = FakeDB(account={"uuid": "acc-1", "email": "dev@example.org"},
                session=("token-abc", None, "sess-1"))
    resp = _client(db).get("/login")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/my/dashboard"
    assert "djehuty_session=token-abc" in resp.headers["set-cookie"]


def test_login_automatic_missing_account_is_403(auth_config, monkeypatch):
    monkeypatch.setattr(config, "automatic_login_email", "ghost@example.org", raising=False)
    db = FakeDB(account=None)
    resp = _client(db).get("/login")
    assert resp.status_code == 403


def test_login_403_renders_html_for_browsers(auth_config, monkeypatch):
    # A browser (Accept: text/html) gets the 403 HTML page, not JSON.
    monkeypatch.setattr(config, "automatic_login_email", "ghost@example.org", raising=False)
    resp = _client(FakeDB(account=None)).get("/login", headers={"Accept": "text/html"})
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text


def test_login_mfa_redirects_to_activation(auth_config, monkeypatch):
    monkeypatch.setattr(config, "automatic_login_email", "dev@example.org", raising=False)
    db = FakeDB(account={"uuid": "acc-1", "email": "dev@example.org"},
                session=("token-abc", "123456", "sess-9"))
    resp = _client(db).get("/login")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/my/sessions/sess-9/activate"
    assert "djehuty_session=token-abc" in resp.headers["set-cookie"]


def test_login_unknown_provider_is_500(auth_config, monkeypatch):
    monkeypatch.setattr(config, "identity_provider", "bogus", raising=False)
    resp = _client(FakeDB()).get("/login")
    assert resp.status_code == 500


def test_logout_normal_clears_cookie_and_redirects_home(auth_config):
    db = FakeDB()
    resp = _client(db, cookies={"djehuty_session": "usertok"}).get("/logout")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert "usertok" in db.deleted_sessions
    # The session cookie is cleared.
    assert 'djehuty_session=""' in resp.headers["set-cookie"] or \
           "djehuty_session=;" in resp.headers["set-cookie"]


def test_logout_impersonation_restores_admin(auth_config):
    db = FakeDB()
    resp = _client(db, cookies={"djehuty_session": "usertok",
                                "impersonator_djehuty_session": "admintok"}).get("/logout")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/users"
    assert "usertok" in db.deleted_sessions
    # The admin's token is set back as the active session.
    assert "djehuty_session=admintok" in resp.headers["set-cookie"]


def test_logout_requires_html_accept(auth_config):
    resp = _client(FakeDB()).get("/logout", headers={"Accept": "application/json"})
    assert resp.status_code == 406


def test_saml_metadata_404_when_not_saml(auth_config, monkeypatch):
    monkeypatch.setattr(config, "identity_provider", "orcid", raising=False)
    resp = _client(FakeDB()).get("/saml/metadata", headers={"Accept": "text/xml"})
    assert resp.status_code == 404


def test_saml_metadata_406_on_wrong_accept(auth_config):
    resp = _client(FakeDB()).get("/saml/metadata", headers={"Accept": "application/json"})
    assert resp.status_code == 406
