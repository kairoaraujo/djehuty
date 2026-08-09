"""Alembic environment for the usage statistics database.

The database URL is not taken from alembic.ini. It is provided by the caller,
either through the ``-x db_url=...`` command line option or the
``DJEHUTY_STATS_DB_URL`` environment variable, so the same djehuty
configuration drives both the application and the migrations.

Phase 0 wires the environment only; the first migration is added in a later
phase.
"""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Target metadata is added together with the schema in a later phase. Keeping
# it None here means autogenerate is not used yet; migrations are hand written.
target_metadata = None


def _database_url() -> str:
    """Resolve the statistics database URL from -x db_url or the environment."""
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("db_url") or os.environ.get("DJEHUTY_STATS_DB_URL")
    if not url:
        raise RuntimeError(
            "No statistics database URL. Pass -x db_url=... or set DJEHUTY_STATS_DB_URL."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in offline mode, emitting SQL to stdout."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=config.get_main_option("version_table"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=config.get_main_option("version_table"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
