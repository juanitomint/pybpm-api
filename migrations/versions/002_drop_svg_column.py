"""Drop svg column from bpm_models — SVGs now live on disk.

Revision ID: 002_drop_svg_column
Revises: 380f18722a18
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_drop_svg_column"
down_revision: str | Sequence[str] | None = "380f18722a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("bpm_models", "svg")


def downgrade() -> None:
    op.add_column(
        "bpm_models",
        sa.Column("svg", sa.Text(), nullable=True),
    )
