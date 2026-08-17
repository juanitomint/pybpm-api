"""add idu column to event_schedules

Revision ID: a006b1514d53
Revises: abc123def456
Create Date: 2026-08-17 01:45:48.293312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a006b1514d53'
down_revision: Union[str, Sequence[str], None] = 'abc123def456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add idu column to event_schedules for user attribution."""
    op.add_column(
        'event_schedules',
        sa.Column('idu', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Remove idu column from event_schedules."""
    op.drop_column('event_schedules', 'idu')
