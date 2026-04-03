"""
FastAPI-based API for djehuty.

This package provides a modern, validated, and documented API layer that
replaces the legacy Werkzeug-based endpoints in ``djehuty.web.wsgi``.

The legacy implementation is deprecated and will be removed after
2027-01-01.  Use ``<api-service>new</api-service>`` in the configuration
file to enable this implementation.
"""

import importlib.metadata

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from djehuty.api.v2.router import router as v2_router
from djehuty.api.v3.router import router as v3_router
from djehuty.api.exceptions import register_exception_handlers


def create_app(db) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    db : djehuty.web.database.SparqlInterface
        The shared database instance from the legacy application.
    """
    app = FastAPI(
        title="Djehuty API",
        summary="Research data repository API for 4TU.ResearchData",
        description=(
            "Djehuty provides a REST API compatible with the Figshare v2 API "
            "and an extended v3 API with additional features.\n\n"
            "- **v2**: Figshare-compatible endpoints under `/v2/`\n"
            "- **v3**: Extended endpoints under `/v3/`\n\n"
            "Source code: [github.com/4TUResearchData/djehuty]"
            "(https://github.com/4TUResearchData/djehuty)"
        ),
        version=importlib.metadata.version("djehuty"),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Number-Of-Records", "Number-Of-Returned-Records"],
    )

    register_exception_handlers(app)

    app.include_router(v2_router)
    app.include_router(v3_router)

    return app
