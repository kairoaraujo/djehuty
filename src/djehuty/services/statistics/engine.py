"""SQLAlchemy engine management for the usage statistics store.

The engine is created lazily from the configured database URL so that importing
this module has no side effects and deployments that do not use the SQL store
pay no cost. Phase 0 only provides the engine factory; the schema and queries
are added in later phases.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_engine: Engine | None = None


def create_statistics_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the statistics database URL."""
    return create_engine(database_url, future=True, pool_pre_ping=True)


def get_engine(database_url: str) -> Engine:
    """Return a process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_statistics_engine(database_url)
    return _engine


def reset_engine() -> None:
    """Dispose and clear the cached engine. Intended for tests."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
