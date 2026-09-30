"""add_signal_resource_id

Revision ID: 2e39fec2af79
Revises: initial_schema
Create Date: 2026-09-30 15:42:34.561251

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e39fec2af79'
down_revision: Union[str, Sequence[str], None] = 'initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "signals",
        sa.Column("resource_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("signals", "resource_id")
