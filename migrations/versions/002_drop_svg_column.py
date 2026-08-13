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
    """Drop svg column if it exists (SVGs now live on disk).

    Uses a PostgreSQL DO block to safely check for the column's existence
    before dropping, avoiding transaction abort on missing columns.
    """
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'bpm_models' AND column_name = 'svg'
            ) THEN
                ALTER TABLE bpm_models DROP COLUMN svg;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.add_column(
        "bpm_models",
        sa.Column("svg", sa.Text(), nullable=True),
    )
