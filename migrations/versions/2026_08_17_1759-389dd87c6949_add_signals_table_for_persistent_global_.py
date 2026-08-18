"""add signals table for persistent global events

Revision ID: 389dd87c6949
Revises: a006b1514d53
Create Date: 2026-08-17 17:59:29.950056

Creates the signals table to persist global signal events that remain active
until fired (all matching schedules dispatched) — enabling cross-case /
cross-model signal communication between EndSignalEvent throwers and IntermediateSignalEventCatching catchers.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '389dd87c6949'
down_revision: Union[str, Sequence[str], None] = 'a006b1514d53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create signals table and indexes for persistent global event storage."""
    op.create_table(
        "signals",
        sa.Column("idsignal", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.String(length=10),
            sa.ForeignKey("cases.idcase"),
            nullable=True,  # global signals have no case context
        ),
        sa.Column(
            "idwf",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idsignal"),
    )

    # Index on signal name for catcher lookups.
    op.create_index(
        op.f("ix_signals_name"),
        "signals",
        ["name"],
        unique=False,
    )



def downgrade() -> None:
    """Drop signals table and indexes."""
    op.drop_index(op.f("ix_signals_name"), table_name="signals")
    op.drop_table("signals")
