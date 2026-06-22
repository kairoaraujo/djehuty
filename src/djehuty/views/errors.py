"""Shared AS-IS error responses for the FastAPI UI surface (and auth).

Faithful port of the legacy ``error_400`` / ``error_403`` / ``error_404`` /
``error_406`` / ``error_500`` helpers from ``djehuty.web.wsgi``. The 403 and 404
helpers render the HTML error templates for HTML clients and fall back to JSON
for everyone else, exactly as legacy did. 400/406 carry no template; 500 is an
empty body, also as legacy.
"""

import logging

from fastapi import Request
from fastapi.responses import (
    Response,
    JSONResponse,
    PlainTextResponse,
    HTMLResponse,
)

from djehuty.web.config import config
from djehuty.services.content_negotiation import accepts_html
from djehuty.views.templating import render_template, COOKIE_KEY, IMPERSONATOR_COOKIE_KEY

_log = logging.getLogger(__name__)


def _html_error(db, request: Request, template_name: str, status_code: int) -> Response:
    token        = request.cookies.get(COOKIE_KEY)
    impersonator = request.cookies.get(IMPERSONATOR_COOKIE_KEY)
    html = render_template(db, token, impersonator, request.url.path, template_name)
    response = HTMLResponse(content=html, status_code=status_code)
    response.headers["Server"] = config.site_name
    return response


def error_400(message, code) -> Response:
    """HTTP 400 with a single error message (JSON)."""
    return JSONResponse(status_code=400, content={"message": message, "code": code})


def error_403(db, request: Request, audit_log_message=None) -> Response:
    """HTTP 403: 403.html for HTML clients, JSON otherwise."""
    if audit_log_message is not None:
        _log.info(audit_log_message)
    if accepts_html(request.headers.get("Accept"), strict=True):
        return _html_error(db, request, "403.html", 403)
    return JSONResponse(status_code=403, content={"message": "Not allowed."})


def error_404(db, request: Request, audit_log_message=None) -> Response:
    """HTTP 404: 404.html for HTML clients, JSON otherwise."""
    if audit_log_message is not None:
        _log.info(audit_log_message)
    if accepts_html(request.headers.get("Accept"), strict=True):
        return _html_error(db, request, "404.html", 404)
    return JSONResponse(status_code=404,
                        content={"message": "This resource does not exist."})


def error_406(allowed_formats) -> Response:
    """HTTP 406 (plain text), listing the acceptable formats."""
    return PlainTextResponse(f"Acceptable formats: {allowed_formats}", status_code=406)


def error_500(audit_log_message=None) -> Response:
    """HTTP 500 with an empty body, as legacy."""
    if audit_log_message is None:
        audit_log_message = "An unexpected error has occurred (HTTP 500)."
    _log.error(audit_log_message)
    return Response(content="", status_code=500)
