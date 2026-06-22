"""FastAPI authentication surface for djehuty (login / logout / SAML).

A faithful AS-IS port of the legacy Werkzeug auth handlers in
``djehuty.web.wsgi`` (``ui_login``, ``ui_logout``, ``saml_metadata``). The
framework-neutral machinery lives in ``djehuty.services`` (``saml``, ``orcid``,
``sram``, ``content_negotiation``); this package only translates HTTP <-> those
services. Part of the wsgi.py -> FastAPI migration; delete the legacy handlers
once ``web-service: new`` is the default.
"""

from djehuty.auth.router import router

__all__ = ["router"]
