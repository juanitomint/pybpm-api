"""add_tasktype_to_tokens

Revision ID: 6061725fc49f
Revises: bb54aeb1873e
Create Date: 2026-08-23 21:58:41.575680

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6061725fc49f'
down_revision: Union[str, Sequence[str], None] = 'bb54aeb1873e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tokens',
        sa.Column('tasktype', sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tokens', 'tasktype')
