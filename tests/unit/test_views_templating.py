"""Unit tests for the shared UI templating foundation (djehuty.ui).

Pins the faithful behaviour of the legacy __render_template page-context builder
and the error helpers: 403/404 render the HTML page for strict-HTML clients and
fall back to JSON otherwise; the full site chrome renders for both anonymous and
logged-in contexts.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from djehuty.views import templating, errors


class FakeDB:
    """A db double exposing the privilege methods the page context needs."""
    def __init__(self, account=None):
        self._account = account

    def account_by_session_token(self, token):
        return self._account

    def is_depositor(self, token, account=None):
        return False

    def __getattr__(self, name):
        # may_review / may_administer / may_impersonate / may_query /
        # may_review_institution / may_review_integrity / may_review_quotas.
        if name.startswith("may_"):
            return lambda *a, **k: False
        raise AttributeError(name)


def test_render_template_anonymous_renders_full_document():
    html = templating.render_template(FakeDB(), None, None, "/", "403.html")
    assert "<html" in html and "</html>" in html
    assert "not allowed" in html.lower()


def test_render_template_logged_in_renders_full_document():
    account = {"uuid": "acc-1", "first_name": "Ada", "last_name": "Lovelace"}
    html = templating.render_template(FakeDB(account), "tok", None, "/my/dashboard", "404.html")
    assert "<html" in html and "</html>" in html


def test_page_context_anonymous_has_no_session():
    ctx = templating.page_context(FakeDB(), None, None, "/")
    assert ctx["is_logged_in"] is False
    assert ctx["session_token"] is None
    assert ctx["impersonating_account"] is None
    assert "nonce" in ctx and ctx["path"] == "/"


def test_page_context_impersonation_only_with_cookie():
    account = {"uuid": "acc-1"}
    db = FakeDB(account)
    # No impersonator token -> not impersonating.
    assert templating.page_context(db, "tok", None, "/")["impersonating_account"] is None
    # Impersonator token present -> the current account is the impersonated one.
    ctx = templating.page_context(db, "tok", "admintok", "/")
    assert ctx["impersonating_account"] == account
    assert ctx["session_token"] == "tok"


# --- error helpers ----------------------------------------------------------

def _error_app(db):
    app = FastAPI()

    @app.get("/e403")
    def e403(request: Request):
        return errors.error_403(db, request)

    @app.get("/e404")
    def e404(request: Request):
        return errors.error_404(db, request)

    return TestClient(app)


def test_error_403_html_for_html_clients():
    resp = _error_app(FakeDB()).get("/e403", headers={"Accept": "text/html"})
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text


def test_error_403_json_for_non_html_clients():
    resp = _error_app(FakeDB()).get("/e403", headers={"Accept": "application/json"})
    assert resp.status_code == 403
    assert resp.json() == {"message": "Not allowed."}


def test_error_404_html_and_json():
    client = _error_app(FakeDB())
    html = client.get("/e404", headers={"Accept": "text/html"})
    assert html.status_code == 404 and "<html" in html.text
    js = client.get("/e404", headers={"Accept": "application/json"})
    assert js.status_code == 404
    assert js.json() == {"message": "This resource does not exist."}


def test_error_400_406_500_status_codes():
    assert errors.error_400("bad", "Code").status_code == 400
    assert errors.error_406("text/html").status_code == 406
    assert errors.error_500().status_code == 500
    # 500 has an empty body, faithful to legacy.
    assert errors.error_500().body == b""
