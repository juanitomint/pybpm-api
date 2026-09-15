"""add_source_to_permission_groups

Revision ID: 2502246e3626
Revises: fb87c502ffe8
Create Date: 2026-09-15 20:16:41.490562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2502246e3626'
down_revision: Union[str, Sequence[str], None] = 'fb87c502ffe8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source column to permission_groups."""
    op.add_column(
        "permission_groups",
        sa.Column("source", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Remove source column from permission_groups."""
    op.drop_column("permission_groups", "source")
