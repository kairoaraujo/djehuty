"""SQL based usage statistics service.

Framework neutral service for recording and querying usage statistics
(views, downloads, git clones). It is only active when a statistics database
is configured; otherwise djehuty keeps recording statistics in the RDF store.

This service is attached as ``app.state.statistics`` in
``djehuty.application.create_app`` and exposed through the ``get_statistics``
dependency, mirroring ``get_db`` and ``get_email``.

The ingest buffer and the query methods are added in later phases. See
design-docs/usage-statistics-sql-store.md and
design-docs/usage-statistics-implementation-plan.md for the design.
"""

from djehuty.services.statistics.engine import (
    create_statistics_engine,
    get_engine,
    reset_engine,
)
from djehuty.services.statistics.migrate import upgrade_to_head
from djehuty.services.statistics.schema import log_events, metadata

__all__ = [
    "create_statistics_engine",
    "get_engine",
    "reset_engine",
    "upgrade_to_head",
    "log_events",
    "metadata",
]
