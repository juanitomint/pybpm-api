"""Add BpmCase, Token, and TokenHistory models

Revision ID: 81dfbb9a3828
Revises: 002_drop_svg_column
Create Date: 2026-08-11 13:50:35.878493

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "81dfbb9a3828"
down_revision: str | Sequence[str] | None = "002_drop_svg_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add BpmCase, Token, and TokenHistory tables."""

    # --- bpm_cases table ---
    op.create_table(
        "bpm_cases",
        sa.Column("idcase", sa.String(length=32), primary_key=True),
        sa.Column("idwf", sa.String(length=255), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column(
            "initiator_id",
            sa.Integer(),
            sa.ForeignKey("users.idu", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("data", sa.JSON()),
        sa.Column("locked_by", sa.Integer()),
        sa.Column("locked_date", sa.DateTime(timezone=True)),
        sa.Column("run_manual", sa.Boolean(), server_default="false"),
        sa.Column("parent", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["idwf"], ["bpm_models.idwf"], ondelete="CASCADE"),
    )

    # --- bpm_tokens table ---
    op.create_table(
        "bpm_tokens",
        sa.Column("idtoken", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("idwf", sa.String(length=255), nullable=False, index=True),
        sa.Column("case_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("resource_id", sa.String(1024), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("assign", sa.JSON()),
        sa.Column("external_data", sa.JSON()),
        sa.Column("check_date", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer(), server_default="0"),
        sa.Column("locked_by", sa.Integer()),
        sa.Column("locked_date", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["idwf"], ["bpm_models.idwf"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["bpm_cases.idcase"], ondelete="CASCADE"),
    )

    # --- bpm_token_history table ---
    op.create_table(
        "bpm_token_history",
        sa.Column("idhistory", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("idwf", sa.String(length=255), nullable=False, index=True),
        sa.Column("case_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("resource_id", sa.String(1024), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("check_date", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer(), server_default="0"),
        sa.Column("name", sa.String(255)),
        sa.Column(
            "iduser", sa.Integer(), sa.ForeignKey("users.idu", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["idwf"], ["bpm_models.idwf"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["bpm_cases.idcase"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    """Remove BpmCase, Token, and TokenHistory tables."""
    op.drop_table("bpm_token_history")
    op.drop_table("bpm_tokens")
    op.drop_table("bpm_cases")
