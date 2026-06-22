"""FastAPI response builders for the UI surface.

Small wrappers that mirror the legacy ``response()``/``__render_template``
behaviour: render a template, return it with the right media type, and set the
``Server`` header to the configured site name.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from djehuty.web.config import config
from djehuty.views.templating import (
    render_template,
    render_plain_template,
    COOKIE_KEY,
    IMPERSONATOR_COOKIE_KEY,
)


def _with_server_header(response: Response) -> Response:
    response.headers["Server"] = config.site_name
    return response


def render_page(db, request: Request, template_name: str,
                status_code: int = 200, **context) -> HTMLResponse:
    """Render a full HTML page with the shared page context.

    Resolves the session/impersonator tokens from the request cookies, exactly
    as the legacy ``__render_template`` did from the Werkzeug request.
    """
    token        = request.cookies.get(COOKIE_KEY)
    impersonator = request.cookies.get(IMPERSONATOR_COOKIE_KEY)
    html = render_template(db, token, impersonator, request.url.path,
                           template_name, **context)
    return _with_server_header(HTMLResponse(content=html, status_code=status_code))


def render_media(template_name: str, media_type: str, **context) -> Response:
    """Render a non-HTML template (css/svg/xml) with only the given context."""
    body = render_plain_template(template_name, **context)
    return _with_server_header(Response(content=body, media_type=media_type))
