"""add_idu_to_permission_repository

Revision ID: fb87c502ffe8
Revises: initial_schema
Create Date: 2026-09-14 23:22:52.715573

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb87c502ffe8'
down_revision: Union[str, Sequence[str], None] = 'initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add idu column to permission_repository."""
    op.add_column('permission_repository', sa.Column('idu', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove idu column from permission_repository."""
    op.drop_column('permission_repository', 'idu')
