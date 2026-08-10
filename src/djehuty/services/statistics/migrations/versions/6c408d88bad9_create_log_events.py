"""create log_events

Revision ID: 6c408d88bad9
Revises:
Create Date: 2026-08-10 09:12:38.299521
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c408d88bad9"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "log_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("item_uuid", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_log_events_item",
        "log_events",
        ["item_uuid", "event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_log_events_created_at",
        "log_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_log_events_created_at", table_name="log_events")
    op.drop_index("ix_log_events_item", table_name="log_events")
    op.drop_table("log_events")
