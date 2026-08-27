"""initial schema — consolidated from all models

Revision ID: initial_schema
Revises:
Create Date: 2026-08-26 00:00:00.000000

This migration replaces all prior migrations. It creates the full schema
from the current SQLAlchemy models.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from current models."""

    # -- event_schedules ------------------------------------------------------
    op.create_table(
        "event_schedules",
        sa.Column("idschedule", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=10), nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column("trigger_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "schedule_type",
            sa.String(length=50),
            nullable=False,
            server_default="timer",
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("idu", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idschedule"),
    )
    op.create_index(
        op.f("ix_event_schedules_idu"), "event_schedules", ["idu"], unique=False
    )
    op.create_index(
        op.f("ix_event_schedules_trigger_time"),
        "event_schedules",
        ["trigger_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_event_schedules_status"), "event_schedules", ["status"], unique=False
    )

    # -- groups ---------------------------------------------------------------
    op.create_table(
        "groups",
        sa.Column("idgroup", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.Column("idsup", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("idgroup"),
        sa.UniqueConstraint("name"),
    )

    # -- permission_repository ------------------------------------------------
    op.create_table(
        "permission_repository",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column(
            "check_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_permission_repository_path"),
        "permission_repository",
        ["path"],
        unique=False,
    )

    # -- users ----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("idu", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nick", sa.String(length=255), nullable=False),
        sa.Column("pass_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("lastname", sa.String(length=128), nullable=True),
        sa.Column("perm", sa.JSON(), nullable=True),
        sa.Column("idgroup", sa.Integer(), nullable=True),
        sa.Column("last_acc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("token", sa.String(length=255), nullable=True),
        sa.Column("notification_by_email", sa.String(length=10), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("idu"),
        sa.UniqueConstraint("nick"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_users_idgroup"), "users", ["idgroup"], unique=False)

    # -- messages -------------------------------------------------------------
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
            "folder", sa.String(length=32), nullable=False, server_default="inbox"
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tag", sa.String(length=128), nullable=True),
        sa.Column(
            "checkdate",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idmessage"),
        sa.ForeignKeyConstraint(["to_idu"], ["users.idu"]),
        sa.ForeignKeyConstraint(["from_idu"], ["users.idu"]),
    )
    op.create_index(op.f("ix_messages_folder"), "messages", ["folder"], unique=False)
    op.create_index(
        op.f("ix_messages_checkdate"), "messages", ["checkdate"], unique=False
    )
    op.create_index(op.f("ix_messages_to_idu"), "messages", ["to_idu"], unique=False)

    # -- models ---------------------------------------------------------------
    op.create_table(
        "models",
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("idwf"),
        sa.ForeignKeyConstraint(["created_by"], ["users.idu"]),
    )

    # -- permission_groups ----------------------------------------------------
    op.create_table(
        "permission_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("idgroup", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["idgroup"], ["groups.idgroup"]),
    )
    op.create_index(
        op.f("ix_permission_groups_path"), "permission_groups", ["path"], unique=False
    )

    # -- users_groups ---------------------------------------------------------
    op.create_table(
        "users_groups",
        sa.Column("iduser", sa.Integer(), nullable=False),
        sa.Column("idgroup", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("iduser", "idgroup"),
        sa.ForeignKeyConstraint(["iduser"], ["users.idu"]),
        sa.ForeignKeyConstraint(["idgroup"], ["groups.idgroup"]),
    )

    # -- cases ----------------------------------------------------------------
    op.create_table(
        "cases",
        sa.Column("idcase", sa.String(length=32), nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="open"
        ),
        sa.Column("initiator_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("locked_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_manual", sa.Boolean(), server_default="false", nullable=True),
        sa.Column("parent", sa.JSON(), nullable=True),
        sa.Column("closer", sa.String(length=1024), nullable=True),
        sa.Column("checkoutdate", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idcase"),
        sa.ForeignKeyConstraint(["idwf"], ["models.idwf"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiator_id"], ["users.idu"], ondelete="SET NULL"),
    )
    op.create_index(
        op.f("ix_cases_initiator_id"), "cases", ["initiator_id"], unique=False
    )
    op.create_index(op.f("ix_cases_idwf"), "cases", ["idwf"], unique=False)

    # -- token_history --------------------------------------------------------
    op.create_table(
        "token_history",
        sa.Column("idhistory", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("check_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("iduser", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idhistory"),
        sa.ForeignKeyConstraint(["idwf"], ["models.idwf"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.idcase"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["iduser"], ["users.idu"], ondelete="SET NULL"),
    )
    op.create_index(
        op.f("ix_token_history_idwf"), "token_history", ["idwf"], unique=False
    )
    op.create_index(
        op.f("ix_token_history_case_id"), "token_history", ["case_id"], unique=False
    )

    # -- tokens ---------------------------------------------------------------
    op.create_table(
        "tokens",
        sa.Column("idtoken", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("assign", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("idu", sa.Integer(), nullable=True),
        sa.Column("external_data", sa.JSON(), nullable=True),
        sa.Column("check_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("tasktype", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idtoken"),
        sa.UniqueConstraint(
            "case_id", "resource_id", "idwf", name="uq_tokens_case_resource_idwf"
        ),
        sa.ForeignKeyConstraint(["idwf"], ["models.idwf"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.idcase"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_tokens_idwf"), "tokens", ["idwf"], unique=False)
    op.create_index(
        op.f("ix_tokens_resource_id"), "tokens", ["resource_id"], unique=False
    )
    op.create_index(op.f("ix_tokens_idu"), "tokens", ["idu"], unique=False)
    op.create_index(op.f("ix_tokens_case_id"), "tokens", ["case_id"], unique=False)

    # -- signals --------------------------------------------------------------
    op.create_table(
        "signals",
        sa.Column("idsignal", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("case_id", sa.String(length=10), nullable=True),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("idsignal"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.idcase"]),
    )
    op.create_index(op.f("ix_signals_name"), "signals", ["name"], unique=False)


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("signals")
    op.drop_table("tokens")
    op.drop_table("token_history")
    op.drop_table("cases")
    op.drop_table("users_groups")
    op.drop_table("permission_groups")
    op.drop_table("models")
    op.drop_table("messages")
    op.drop_table("users")
    op.drop_table("permission_repository")
    op.drop_table("groups")
    op.drop_table("event_schedules")
