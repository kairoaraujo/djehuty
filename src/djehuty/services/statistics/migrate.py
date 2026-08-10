"""Programmatic Alembic runner for the usage statistics database.

Lets djehuty bring the statistics schema up to head at start up without shelling
out to the Alembic CLI. The database URL is passed in from the djehuty
configuration.
"""

import os

from alembic import command
from alembic.config import Config

_HERE = os.path.dirname(os.path.abspath(__file__))
_ALEMBIC_INI = os.path.join(_HERE, "alembic.ini")


def _alembic_config(database_url: str) -> Config:
    """Build an Alembic Config pointed at the statistics migrations.

    env.py resolves the URL from the ``-x db_url=...`` argument; we set it via
    ``cmd_opts`` so ``context.get_x_argument`` sees it exactly as the CLI would.
    """
    cfg = Config(_ALEMBIC_INI)
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url={database_url}"]})()
    return cfg


def upgrade_to_head(database_url: str) -> None:
    """Upgrade the statistics database to the latest revision."""
    command.upgrade(_alembic_config(database_url), "head")
