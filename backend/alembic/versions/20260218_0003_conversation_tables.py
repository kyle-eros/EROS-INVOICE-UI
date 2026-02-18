"""Create conversation thread/message/event/dedup tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260218_0003"
down_revision = "20260218_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_threads",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("external_contact", sa.String(length=256), nullable=False),
        sa.Column("creator_id", sa.String(length=128), nullable=True),
        sa.Column("creator_name", sa.String(length=256), nullable=True),
        sa.Column("invoice_id", sa.String(length=128), nullable=True),
        sa.Column("provider_thread_ref", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("auto_reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_preview", sa.Text(), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index("ix_conversation_threads_channel", "conversation_threads", ["channel"], unique=False)
    op.create_index("ix_conversation_threads_creator_id", "conversation_threads", ["creator_id"], unique=False)
    op.create_index("ix_conversation_threads_invoice_id", "conversation_threads", ["invoice_id"], unique=False)
    op.create_index("ix_conversation_threads_status", "conversation_threads", ["status"], unique=False)
    op.create_index("ix_conversation_threads_updated_at", "conversation_threads", ["updated_at"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("delivery_state", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=True),
        sa.Column("policy_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.thread_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("provider_message_id"),
    )
    op.create_index("ix_conversation_messages_thread_id", "conversation_messages", ["thread_id"], unique=False)
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"], unique=False)

    op.create_table(
        "conversation_events",
        sa.Column("event_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, autoincrement=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.thread_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_conversation_events_thread_id", "conversation_events", ["thread_id"], unique=False)

    op.create_table(
        "webhook_receipts_dedup",
        sa.Column("receipt_key", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("receipt_key"),
    )


def downgrade() -> None:
    op.drop_table("webhook_receipts_dedup")

    op.drop_index("ix_conversation_events_thread_id", table_name="conversation_events")
    op.drop_table("conversation_events")

    op.drop_index("ix_conversation_messages_created_at", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_thread_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")

    op.drop_index("ix_conversation_threads_updated_at", table_name="conversation_threads")
    op.drop_index("ix_conversation_threads_status", table_name="conversation_threads")
    op.drop_index("ix_conversation_threads_invoice_id", table_name="conversation_threads")
    op.drop_index("ix_conversation_threads_creator_id", table_name="conversation_threads")
    op.drop_index("ix_conversation_threads_channel", table_name="conversation_threads")
    op.drop_table("conversation_threads")
