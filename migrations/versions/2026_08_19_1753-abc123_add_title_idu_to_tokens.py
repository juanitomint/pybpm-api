"""add title and idu columns to tokens table

Revision ID: abc123_add_title_idu_to_tokens
Revises: 389dd87c6949
Create Date: 2026-08-19 17:53:00.000000

Adds title (shape name) and idu (claiming user ID) columns to the tokens table,
mirroring legacy MongoDB token documents which stored shape 'name' and the user
ID that claimed/executed the task.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "abc123_add_title_idu_to_tokens"
down_revision: str | None = "389dd87c6949"
branch_labels: str | dict[str, str] | tuple[str | dict[str, str], ...] | None = None
depends_on: str | list[str] | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("tokens", sa.Column("title", sa.String(512), nullable=True))
    op.add_column("tokens", sa.Column("idu", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_tokens_idu"), "tokens", ["idu"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tokens_idu"), table_name="tokens")
    op.drop_column("tokens", "idu")
    op.drop_column("tokens", "title")
