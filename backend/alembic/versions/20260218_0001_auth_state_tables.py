"""Create auth state tables for passkeys, revocations, and login throttling."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260218_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_passkeys",
        sa.Column("creator_id", sa.String(length=128), nullable=False),
        sa.Column("creator_name", sa.String(length=256), nullable=False),
        sa.Column("passkey_hash", sa.String(length=64), nullable=False),
        sa.Column("display_prefix", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("creator_id"),
        sa.UniqueConstraint("passkey_hash"),
    )

    op.create_table(
        "creator_auth_state",
        sa.Column("creator_id", sa.String(length=128), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("creator_id"),
    )

    op.create_table(
        "auth_failed_login_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_ip", sa.String(length=128), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_failed_login_attempts_client_ip",
        "auth_failed_login_attempts",
        ["client_ip"],
        unique=False,
    )
    op.create_index(
        "ix_auth_failed_login_attempts_attempted_at",
        "auth_failed_login_attempts",
        ["attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_failed_login_attempts_client_ip_attempted_at",
        "auth_failed_login_attempts",
        ["client_ip", "attempted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_failed_login_attempts_client_ip_attempted_at",
        table_name="auth_failed_login_attempts",
    )
    op.drop_index("ix_auth_failed_login_attempts_attempted_at", table_name="auth_failed_login_attempts")
    op.drop_index("ix_auth_failed_login_attempts_client_ip", table_name="auth_failed_login_attempts")
    op.drop_table("auth_failed_login_attempts")
    op.drop_table("creator_auth_state")
    op.drop_table("creator_passkeys")
