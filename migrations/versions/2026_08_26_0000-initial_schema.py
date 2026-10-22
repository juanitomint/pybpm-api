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
    # -- groups -----------------------------------------------------------------
    op.create_table(
        "groups",
        sa.Column("idgroup", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.Column("idsup", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("idgroup"),
    )
    op.create_index(op.f("ix_groups_name"), "groups", ["name"], unique=True)

    # -- users ------------------------------------------------------------------
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
        sa.Column("notification_by_email", sa.String(length=3), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("idu"),
    )
    op.create_index(op.f("ix_users_nick"), "users", ["nick"], unique=True)
    op.create_index(op.f("ix_users_idgroup"), "users", ["idgroup"], unique=False)
    op.create_index(op.f("ix_users_token"), "users", ["token"], unique=True)

    # -- models -----------------------------------------------------------------
    op.create_table(
        "models",
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("idwf"),
        sa.ForeignKeyConstraint(["created_by"], ["users.idu"]),
    )
    op.create_index(op.f("ix_models_folder"), "models", ["folder"], unique=False)

    # -- cases ------------------------------------------------------------------
    op.create_table(
        "cases",
        sa.Column("idcase", sa.String(length=32), nullable=False),
        sa.Column(
            "idwf",
            sa.String(length=255),
            sa.ForeignKey("models.idwf", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "initiator_id",
            sa.Integer(),
            sa.ForeignKey("users.idu", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("locked_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "run_manual",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=True,
        ),
        sa.Column("parent", sa.JSON(), nullable=True),
        sa.Column("closer", sa.String(length=1024), nullable=True),
        sa.Column("checkoutdate", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idcase"),
    )
    op.create_index(op.f("ix_cases_idwf"), "cases", ["idwf"], unique=False)
    op.create_index(
        op.f("ix_cases_initiator_id"), "cases", ["initiator_id"], unique=False
    )

    # -- tokens -----------------------------------------------------------------
    op.create_table(
        "tokens",
        sa.Column(
            "idtoken",
            sa.dialects.postgresql.UUID(),
            server_default=sa.func.uuidv7(),
            nullable=False,
        ),
        sa.Column(
            "idwf",
            sa.String(length=255),
            sa.ForeignKey("models.idwf", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.String(length=32),
            sa.ForeignKey("cases.idcase", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("assign", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("idu", sa.Integer(), nullable=True),
        sa.Column("external_data", sa.JSON(), nullable=True),
        sa.Column("check_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "run_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("tasktype", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idtoken"),
        sa.UniqueConstraint(
            "case_id", "resource_id", "idwf", name="uq_tokens_case_resource_idwf"
        ),
    )
    op.create_index(
        op.f("ix_tokens_idwf_case_resource"),
        "tokens",
        ["idwf", "case_id", "resource_id"],
        unique=False,
    )

    # -- token_history ------------------------------------------------------------
    op.create_table(
        "token_history",
        sa.Column(
            "idhistory",
            sa.dialects.postgresql.UUID(),
            server_default=sa.func.uuidv7uuidv7(),
            nullable=False,
        ),
        sa.Column(
            "idwf",
            sa.String(length=255),
            sa.ForeignKey("models.idwf", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.String(length=32),
            sa.ForeignKey("cases.idcase", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("check_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "run_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "iduser",
            sa.Integer(),
            sa.ForeignKey("users.idu", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idhistory"),
    )
    op.create_index(
        op.f("ix_token_history_idwf"),
        "token_history",
        ["idwf"],
        unique=False,
    )
    op.create_index(
        op.f("ix_token_history_case_id"),
        "token_history",
        ["case_id"],
        unique=False,
    )

    # -- permission_repository --------------------------------------------------
    op.create_table(
        "permission_repository",
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("idu", sa.Integer(), nullable=True),
        sa.Column(
            "check_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("path"),
    )
    op.create_index(
        op.f("ix_permission_repository_path"),
        "permission_repository",
        ["path"],
        unique=False,
    )

    # -- permission_groups ------------------------------------------------------
    op.create_table(
        "permission_groups",
        sa.Column(
            "idgroup",
            sa.Integer(),
            sa.ForeignKey("groups.idgroup"),
            nullable=False,
        ),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("idgroup", "path"),
    )
    op.create_index(
        op.f("ix_permission_groups_path"),
        "permission_groups",
        ["path"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_permission_group_idgroup_path",
        "permission_groups",
        ["idgroup", "path"],
    )

    # -- users_groups -----------------------------------------------------------
    op.create_table(
        "users_groups",
        sa.Column(
            "iduser",
            sa.Integer(),
            sa.ForeignKey("users.idu"),
            nullable=False,
        ),
        sa.Column(
            "idgroup",
            sa.Integer(),
            sa.ForeignKey("groups.idgroup"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("iduser", "idgroup"),
    )

    # -- messages ---------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("idmessage", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "to_idu",
            sa.Integer(),
            sa.ForeignKey("users.idu"),
            nullable=False,
        ),
        sa.Column(
            "from_idu",
            sa.Integer(),
            sa.ForeignKey("users.idu"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "folder",
            sa.String(length=32),
            server_default=sa.text("'inbox'"),
            nullable=False,
        ),
        sa.Column(
            "is_read",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_starred",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(length=128), nullable=True),
        sa.Column(
            "checkdate",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idmessage"),
    )
    op.create_index(op.f("ix_messages_to_idu"), "messages", ["to_idu"], unique=False)
    op.create_index(op.f("ix_messages_folder"), "messages", ["folder"], unique=False)
    op.create_index(
        op.f("ix_messages_checkdate"), "messages", ["checkdate"], unique=False
    )

    # -- event_schedules --------------------------------------------------------
    op.create_table(
        "event_schedules",
        sa.Column("idschedule", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=10), nullable=False),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("resource_id", sa.String(length=1024), nullable=False),
        sa.Column(
            "trigger_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idschedule"),
    )
    op.create_index(
        op.f("ix_event_schedules_trigger_time"),
        "event_schedules",
        ["trigger_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_event_schedules_status"),
        "event_schedules",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_event_schedules_idu"), "event_schedules", ["idu"], unique=False
    )
    op.create_index(
        op.f("ix_event_schedules_status_trigger_time"),
        "event_schedules",
        ["status", "trigger_time"],
        unique=False,
    )

    # -- signals ----------------------------------------------------------------
    op.create_table(
        "signals",
        sa.Column("idsignal", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "case_id",
            sa.String(length=10),
            sa.ForeignKey("cases.idcase"),
            nullable=True,
        ),
        sa.Column("idwf", sa.String(length=255), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("idsignal"),
    )
    op.create_index(op.f("ix_signals_name"), "signals", ["name"], unique=False)


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("signals")
    op.drop_table("event_schedules")
    op.drop_table("messages")
    op.drop_table("users_groups")
    op.drop_table("permission_groups")
    op.drop_table("permission_repository")
    op.drop_table("token_history")
    op.drop_table("tokens")
    op.drop_table("cases")
    op.drop_table("models")
    op.drop_table("users")
    op.drop_table("groups")
