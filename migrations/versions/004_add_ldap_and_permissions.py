"""Add LDAP-style RBAC fields and permission tables

Mirrors the MongoDB dna3 collections: groups (desc, idsup),
users (perm, idgroup), perm.groups, perm.repository.

Revision ID: 004_add_ldap_and_permissions
Revises: 002_drop_svg_column
Create Date: 2026-08-12 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_ldap_and_permissions"
down_revision: str | Sequence[str] | None = "81dfbb9a3828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add missing MongoDB fields and create permission tables."""

    # --- groups table: add desc and idsup columns (MongoDB 'groups') ---
    op.add_column(
        "groups",
        sa.Column("desc", sa.Text(), nullable=True),  # MongoDB 'desc' — group description
    )
    op.add_column(
        "groups",
        sa.Column("idsup", sa.String(length=255), nullable=True),  # MongoDB 'idsup' — supervisor group reference
    )

    # --- users table: add perm and idgroup columns (MongoDB 'users') ---
    op.add_column(
        "users",
        sa.Column("perm", sa.JSON(), nullable=True),  # MongoDB 'perm' — list of permission strings (e.g. ['ADM'])
    )
    op.add_column(
        "users",
        sa.Column("idgroup", sa.Integer(), nullable=True, index=True),  # MongoDB 'idgroup' — group reference FK
    )

    # --- permission_groups table: mirrors MongoDB 'perm.groups' collection ---
    op.create_table(
        "permission_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("path", sa.String(length=255), nullable=False, index=True),  # e.g. 'root/modules/bpm'
        sa.Column("idgroup", sa.Integer(), nullable=False),  # group FK
        sa.ForeignKeyConstraint(["idgroup"], ["groups.idgroup"]),
    )

    # --- permission_repository table: mirrors MongoDB 'perm.repository' collection ---
    op.create_table(
        "permission_repository",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("path", sa.String(length=255), nullable=False, index=True),  # resource path
        sa.Column("source", sa.String(length=64), nullable=True),  # MongoDB 'properties.source' (e.g. 'Setup')
        sa.Column(
            "checkdate",
            sa.DateTime(timezone=True),
            nullable=True,
        ),  # MongoDB 'properties.checkdate'
    )


def downgrade() -> None:
    """Remove added columns and tables."""
    op.drop_table("permission_repository")
    op.drop_table("permission_groups")
    op.drop_column("users", "idgroup")
    op.drop_column("users", "perm")
    op.drop_column("groups", "idsup")
    op.drop_column("groups", "desc")
