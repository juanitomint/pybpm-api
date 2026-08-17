"""Add messages table and user notification fields

Revision ID: 142cd11e9d3e
Revises: 3e4ef1f8ff43
Create Date: 2026-08-16 21:11:59.147480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "142cd11e9d3e"
down_revision: Union[str, Sequence[str], None] = "3e4ef1f8ff43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add messages table and notification/signature columns to users."""

    # -- messages table -------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("idmessage", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("to_idu", sa.Integer(), nullable=False),
        sa.Column("from_idu", sa.Integer(), nullable=True),
        sa.Column(
            "subject",
            sa.String(length=512),
            nullable=False,
            server_default="No Subject",
        ),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "folder",
            sa.String(length=32),
            nullable=False,
            server_default="inbox",
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "is_starred", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("tag", sa.String(length=128), nullable=True),
        sa.Column(
            "checkdate",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["from_idu"], ["users.idu"]),
        sa.ForeignKeyConstraint(["to_idu"], ["users.idu"]),
        sa.PrimaryKeyConstraint("idmessage"),
    )
    op.create_index(op.f("ix_messages_folder"), "messages", ["folder"], unique=False)
    op.create_index(
        op.f("ix_messages_checkdate"), "messages", ["checkdate"], unique=False
    )
    op.create_index(op.f("ix_messages_to_idu"), "messages", ["to_idu"], unique=False)

    # -- user notification fields ---------------------------------------------
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("notification_by_email", sa.String(length=10), nullable=True)
        )
        batch_op.add_column(sa.Column("signature", sa.Text(), nullable=True))


def downgrade() -> None:
    """Reverse the inbox migration."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("signature")
        batch_op.drop_column("notification_by_email")

    op.drop_index(op.f("ix_messages_to_idu"), table_name="messages")
    op.drop_index(op.f("ix_messages_checkdate"), table_name="messages")
    op.drop_index(op.f("ix_messages_folder"), table_name="messages")
    op.drop_table("messages")
