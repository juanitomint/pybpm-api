"""Add event_schedules table for timer/signal/conditional triggers

Revision ID: abc123def456
Revises: 142cd11e9d3e
Create Date: 2026-08-17 01:45:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abc123def456"
down_revision: Union[str, Sequence[str], None] = "142cd11e9d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create event_schedules table for timer/signal/conditional triggers."""

    op.create_table(
        "event_schedules",
        sa.Column("idschedule", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=10), nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column(
            "resource_id",
            sa.String(length=1024),
            nullable=False,
        ),
        sa.Column(
            "trigger_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "schedule_type",
            sa.String(length=50),
            nullable=False,
            server_default="timer",
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            default="pending",
        ),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.idcase"]),
        sa.PrimaryKeyConstraint("idschedule"),
    )

    # Index on trigger_time for scheduler queries: "find all due now"
    op.create_index(
        op.f("ix_event_schedules_trigger_time"),
        "event_schedules",
        ["trigger_time"],
        unique=False,
    )

    # Index on status for filtering pending vs fired/canceled
    op.create_index(
        op.f("ix_event_schedules_status"),
        "event_schedules",
        ["status"],
        unique=False,
    )

    # Composite index for scheduler query: WHERE status='pending' AND trigger_time <= NOW()
    op.create_index(
        op.f("ix_event_schedules_due_now"),
        "event_schedules",
        ["status", "trigger_time"],
        unique=False,
    )


def downgrade() -> None:
    """Drop event_schedules table and indexes."""
    op.drop_index(op.f("ix_event_schedules_due_now"), table_name="event_schedules")
    op.drop_index(op.f("ix_event_schedules_status"), table_name="event_schedules")
    op.drop_index(op.f("ix_event_schedules_trigger_time"), table_name="event_schedules")
    op.drop_table("event_schedules")
