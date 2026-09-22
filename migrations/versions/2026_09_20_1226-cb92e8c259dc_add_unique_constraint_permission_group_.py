"""add_unique_constraint_permission_group_idgroup_path

Revision ID: cb92e8c259dc
Revises: 2502246e3626
Create Date: 2026-09-20 12:26:05.377435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb92e8c259dc'
down_revision: Union[str, Sequence[str], None] = '2502246e3626'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on permission_groups(idgroup, path)."""
    op.create_unique_constraint(
        "uq_permission_group_idgroup_path",
        "permission_groups",
        ["idgroup", "path"],
    )


def downgrade() -> None:
    """Remove unique constraint."""
    op.drop_constraint(
        "uq_permission_group_idgroup_path",
        "permission_groups",
        type_="unique",
    )
