"""Umbrella FastAPI application assembling every migrated web surface.

This is the eventual replacement for ``djehuty.web.wsgi``. It reuses the API
app built by ``djehuty.api.create_app`` (kept as-is) and mounts the additional
sibling surfaces -- currently ``djehuty.auth`` (login/logout/SAML), with
``djehuty.views`` (UI pages) / ``djehuty.exports`` / ``djehuty.iiif`` to follow.

The WSGI dispatcher in ``djehuty.web.ui`` routes the prefixes this app serves
to here and everything else to the legacy server, so the migration proceeds
surface by surface while staying switchable back to legacy.
"""

from fastapi import FastAPI


def create_app(db) -> FastAPI:
    """Create the umbrella FastAPI app (API + auth + future surfaces)."""
    from djehuty.api import create_app as create_api_app
    from djehuty.auth import router as auth_router

    app = create_api_app(db)
    app.include_router(auth_router)
    return app
