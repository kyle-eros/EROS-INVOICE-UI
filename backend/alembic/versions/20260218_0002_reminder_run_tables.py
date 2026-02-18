"""Create reminder run, attempt, outbox, and idempotency tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260218_0002"
down_revision = "20260218_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("triggered_by_type", sa.String(length=32), nullable=False),
        sa.Column("triggered_by_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_payload_json", sa.Text(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evaluated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("escalated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_reminder_runs_run_at", "reminder_runs", ["run_at"], unique=False)
    op.create_index("ix_reminder_runs_status", "reminder_runs", ["status"], unique=False)
    op.create_index("ix_reminder_runs_idempotency_key", "reminder_runs", ["idempotency_key"], unique=False)

    op.create_table(
        "reminder_attempts",
        sa.Column("attempt_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("dispatch_id", sa.String(length=128), nullable=True),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact_target_masked", sa.String(length=256), nullable=True),
        sa.Column("planned_channel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=256), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("channel_results_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reminder_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index("ix_reminder_attempts_run_id", "reminder_attempts", ["run_id"], unique=False)
    op.create_index("ix_reminder_attempts_invoice_id", "reminder_attempts", ["invoice_id"], unique=False)
    op.create_index("ix_reminder_attempts_status", "reminder_attempts", ["status"], unique=False)

    op.create_table(
        "reminder_outbox_messages",
        sa.Column("outbox_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=256), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reminder_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["reminder_attempts.attempt_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("outbox_id"),
    )
    op.create_index("ix_reminder_outbox_run_id", "reminder_outbox_messages", ["run_id"], unique=False)
    op.create_index("ix_reminder_outbox_attempt_id", "reminder_outbox_messages", ["attempt_id"], unique=False)
    op.create_index("ix_reminder_outbox_status", "reminder_outbox_messages", ["status"], unique=False)
    op.create_index("ix_reminder_outbox_available_at", "reminder_outbox_messages", ["available_at"], unique=False)

    op.create_table(
        "reminder_idempotency_keys",
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("response_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reminder_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index("ix_reminder_idempotency_run_id", "reminder_idempotency_keys", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reminder_idempotency_run_id", table_name="reminder_idempotency_keys")
    op.drop_table("reminder_idempotency_keys")

    op.drop_index("ix_reminder_outbox_available_at", table_name="reminder_outbox_messages")
    op.drop_index("ix_reminder_outbox_status", table_name="reminder_outbox_messages")
    op.drop_index("ix_reminder_outbox_attempt_id", table_name="reminder_outbox_messages")
    op.drop_index("ix_reminder_outbox_run_id", table_name="reminder_outbox_messages")
    op.drop_table("reminder_outbox_messages")

    op.drop_index("ix_reminder_attempts_status", table_name="reminder_attempts")
    op.drop_index("ix_reminder_attempts_invoice_id", table_name="reminder_attempts")
    op.drop_index("ix_reminder_attempts_run_id", table_name="reminder_attempts")
    op.drop_table("reminder_attempts")

    op.drop_index("ix_reminder_runs_idempotency_key", table_name="reminder_runs")
    op.drop_index("ix_reminder_runs_status", table_name="reminder_runs")
    op.drop_index("ix_reminder_runs_run_at", table_name="reminder_runs")
    op.drop_table("reminder_runs")
