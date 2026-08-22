"""add unique constraint on (case_id, resource_id, idwf) for tokens

Revision ID: bb54aeb1873e
Revises: abc123_add_title_idu_to_tokens
Create Date: 2026-08-21 19:52:12.153011

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb54aeb1873e'
down_revision: Union[str, Sequence[str], None] = 'abc123_add_title_idu_to_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint so each shape within a case has one token."""
    op.create_unique_constraint(
        'uq_tokens_case_resource_idwf',
        'tokens',
        ['case_id', 'resource_id', 'idwf'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_tokens_case_resource_idwf', 'tokens', type_='unique')
