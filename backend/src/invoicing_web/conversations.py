from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from typing import Any, Protocol

from .conversation_policy import default_eros_reply, evaluate_conversation_policy
from .models import (
    AgentConversationExecuteResponse,
    AgentConversationSuggestResponse,
    ContactChannel,
    ConversationDirection,
    ConversationHandoffResponse,
    ConversationMessageItem,
    ConversationReplyResponse,
    ConversationSenderType,
    ConversationThreadDetailResponse,
    ConversationThreadItem,
    ConversationThreadListResponse,
    ConversationThreadStatus,
    ConversationInboundWebhookResponse,
)
from .notifier import (
    NotifierSender,
    ProviderConversationRequest,
    mask_contact_target,
)


@dataclass(frozen=True)
class ConversationThreadRecord:
    thread_id: str
    channel: ContactChannel
    external_contact: str
    creator_id: str | None
    creator_name: str | None
    invoice_id: str | None
    provider_thread_ref: str | None
    status: ConversationThreadStatus
    auto_reply_count: int
    last_message_preview: str | None
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationMessageRecord:
    message_id: str
    thread_id: str
    direction: ConversationDirection
    sender_type: ConversationSenderType
    body_text: str
    delivery_state: str
    provider_message_id: str | None
    policy_reason: str | None
    created_at: datetime


class ConversationRepository(Protocol):
    def reset(self) -> None: ...

    def register_webhook_receipt(self, *, source: str, receipt_key: str) -> bool: ...

    def create_or_get_thread(
        self,
        *,
        channel: ContactChannel,
        external_contact: str,
        creator_id: str | None,
        creator_name: str | None,
        invoice_id: str | None,
        provider_thread_ref: str | None,
    ) -> ConversationThreadRecord: ...

    def get_thread(self, thread_id: str) -> ConversationThreadRecord | None: ...

    def list_threads(self, *, limit: int) -> list[ConversationThreadRecord]: ...

    def list_messages(self, thread_id: str, *, limit: int) -> list[ConversationMessageRecord]: ...

    def append_message(
        self,
        *,
        thread_id: str,
        direction: ConversationDirection,
        sender_type: ConversationSenderType,
        body_text: str,
        delivery_state: str,
        provider_message_id: str | None,
        policy_reason: str | None,
    ) -> ConversationMessageRecord: ...

    def append_event(self, *, thread_id: str, event_type: str, payload: dict[str, Any]) -> None: ...

    def set_thread_status(self, *, thread_id: str, status: ConversationThreadStatus) -> ConversationThreadRecord: ...

    def increment_auto_reply_count(self, *, thread_id: str) -> ConversationThreadRecord: ...

    def update_delivery_by_provider_message_id(self, *, provider_message_id: str, delivery_state: str) -> bool: ...

    def find_message_by_provider_message_id(self, provider_message_id: str) -> ConversationMessageRecord | None: ...



def _now_utc() -> datetime:
    return datetime.now(timezone.utc)



def _normalize_contact(channel: ContactChannel, value: str) -> str:
    normalized = value.strip()
    if channel == "email":
        return normalized.lower()
    digits = "".join(ch for ch in normalized if ch.isdigit())
    return digits or normalized



def _preview(body_text: str, *, limit: int = 120) -> str:
    clean = " ".join(body_text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._thread_counter = count(1)
        self._message_counter = count(1)
        self._event_counter = count(1)
        self._threads: dict[str, ConversationThreadRecord] = {}
        self._messages_by_thread: dict[str, list[ConversationMessageRecord]] = defaultdict(list)
        self._events_by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._thread_by_contact: dict[tuple[ContactChannel, str], str] = {}
        self._webhook_receipts: set[str] = set()
        self._messages_by_provider_id: dict[str, ConversationMessageRecord] = {}

    def reset(self) -> None:
        self._thread_counter = count(1)
        self._message_counter = count(1)
        self._event_counter = count(1)
        self._threads.clear()
        self._messages_by_thread.clear()
        self._events_by_thread.clear()
        self._thread_by_contact.clear()
        self._webhook_receipts.clear()
        self._messages_by_provider_id.clear()

    def register_webhook_receipt(self, *, source: str, receipt_key: str) -> bool:
        dedup_key = f"{source}:{receipt_key}"
        if dedup_key in self._webhook_receipts:
            return True
        self._webhook_receipts.add(dedup_key)
        return False

    def create_or_get_thread(
        self,
        *,
        channel: ContactChannel,
        external_contact: str,
        creator_id: str | None,
        creator_name: str | None,
        invoice_id: str | None,
        provider_thread_ref: str | None,
    ) -> ConversationThreadRecord:
        normalized_contact = _normalize_contact(channel, external_contact)
        key = (channel, normalized_contact)
        existing_id = self._thread_by_contact.get(key)
        if existing_id is not None:
            existing = self._threads[existing_id]
            updated = ConversationThreadRecord(
                **{
                    **existing.__dict__,
                    "creator_id": existing.creator_id or creator_id,
                    "creator_name": existing.creator_name or creator_name,
                    "invoice_id": existing.invoice_id or invoice_id,
                    "provider_thread_ref": existing.provider_thread_ref or provider_thread_ref,
                    "updated_at": _now_utc(),
                }
            )
            self._threads[existing_id] = updated
            return updated

        now = _now_utc()
        thread_id = f"cthread_{next(self._thread_counter):06d}"
        created = ConversationThreadRecord(
            thread_id=thread_id,
            channel=channel,
            external_contact=external_contact,
            creator_id=creator_id,
            creator_name=creator_name,
            invoice_id=invoice_id,
            provider_thread_ref=provider_thread_ref,
            status="open",
            auto_reply_count=0,
            last_message_preview=None,
            last_inbound_at=None,
            last_outbound_at=None,
            created_at=now,
            updated_at=now,
        )
        self._thread_by_contact[key] = thread_id
        self._threads[thread_id] = created
        return created

    def get_thread(self, thread_id: str) -> ConversationThreadRecord | None:
        return self._threads.get(thread_id)

    def list_threads(self, *, limit: int) -> list[ConversationThreadRecord]:
        ordered = sorted(self._threads.values(), key=lambda value: value.updated_at, reverse=True)
        return ordered[:limit]

    def list_messages(self, thread_id: str, *, limit: int) -> list[ConversationMessageRecord]:
        messages = self._messages_by_thread.get(thread_id, [])
        return messages[-limit:]

    def append_message(
        self,
        *,
        thread_id: str,
        direction: ConversationDirection,
        sender_type: ConversationSenderType,
        body_text: str,
        delivery_state: str,
        provider_message_id: str | None,
        policy_reason: str | None,
    ) -> ConversationMessageRecord:
        thread = self._threads[thread_id]
        message = ConversationMessageRecord(
            message_id=f"cmsg_{next(self._message_counter):06d}",
            thread_id=thread_id,
            direction=direction,
            sender_type=sender_type,
            body_text=body_text,
            delivery_state=delivery_state,
            provider_message_id=provider_message_id,
            policy_reason=policy_reason,
            created_at=_now_utc(),
        )
        self._messages_by_thread[thread_id].append(message)
        if provider_message_id:
            self._messages_by_provider_id[provider_message_id] = message

        update_values: dict[str, Any] = {
            "last_message_preview": _preview(body_text),
            "updated_at": message.created_at,
        }
        if direction == "inbound":
            update_values["last_inbound_at"] = message.created_at
        else:
            update_values["last_outbound_at"] = message.created_at

        self._threads[thread_id] = ConversationThreadRecord(**{**thread.__dict__, **update_values})
        return message

    def append_event(self, *, thread_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._events_by_thread[thread_id].append(
            {
                "event_id": next(self._event_counter),
                "event_type": event_type,
                "payload": payload,
                "created_at": _now_utc().isoformat(),
            }
        )

    def set_thread_status(self, *, thread_id: str, status: ConversationThreadStatus) -> ConversationThreadRecord:
        current = self._threads[thread_id]
        updated = ConversationThreadRecord(
            **{
                **current.__dict__,
                "status": status,
                "updated_at": _now_utc(),
            }
        )
        self._threads[thread_id] = updated
        return updated

    def increment_auto_reply_count(self, *, thread_id: str) -> ConversationThreadRecord:
        current = self._threads[thread_id]
        updated = ConversationThreadRecord(
            **{
                **current.__dict__,
                "auto_reply_count": current.auto_reply_count + 1,
                "updated_at": _now_utc(),
            }
        )
        self._threads[thread_id] = updated
        return updated

    def update_delivery_by_provider_message_id(self, *, provider_message_id: str, delivery_state: str) -> bool:
        message = self._messages_by_provider_id.get(provider_message_id)
        if message is None:
            return False
        messages = self._messages_by_thread[message.thread_id]
        updated: list[ConversationMessageRecord] = []
        for item in messages:
            if item.message_id == message.message_id:
                replacement = ConversationMessageRecord(
                    **{
                        **item.__dict__,
                        "delivery_state": delivery_state,
                    }
                )
                updated.append(replacement)
                self._messages_by_provider_id[provider_message_id] = replacement
            else:
                updated.append(item)
        self._messages_by_thread[message.thread_id] = updated
        return True

    def find_message_by_provider_message_id(self, provider_message_id: str) -> ConversationMessageRecord | None:
        return self._messages_by_provider_id.get(provider_message_id)


SQLALCHEMY_AVAILABLE = True
try:
    from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
except ModuleNotFoundError:
    SQLALCHEMY_AVAILABLE = False


if SQLALCHEMY_AVAILABLE:

    class ConversationsBase(DeclarativeBase):
        pass


    class _ConversationThreadRow(ConversationsBase):
        __tablename__ = "conversation_threads"

        thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
        external_contact: Mapped[str] = mapped_column(String(256), nullable=False)
        creator_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
        creator_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
        invoice_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
        provider_thread_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
        status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
        auto_reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        last_message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
        last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


    class _ConversationMessageRow(ConversationsBase):
        __tablename__ = "conversation_messages"

        message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversation_threads.thread_id"), nullable=False, index=True)
        direction: Mapped[str] = mapped_column(String(16), nullable=False)
        sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
        body_text: Mapped[str] = mapped_column(Text, nullable=False)
        delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
        provider_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
        policy_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


    class _ConversationEventRow(ConversationsBase):
        __tablename__ = "conversation_events"

        event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversation_threads.thread_id"), nullable=False, index=True)
        event_type: Mapped[str] = mapped_column(String(64), nullable=False)
        payload_json: Mapped[str] = mapped_column(Text, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class _WebhookDedupRow(ConversationsBase):
        __tablename__ = "webhook_receipts_dedup"

        receipt_key: Mapped[str] = mapped_column(String(256), primary_key=True)
        source: Mapped[str] = mapped_column(String(32), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class SqlAlchemyConversationRepository:
        def __init__(self, database_url: str) -> None:
            if not database_url:
                raise RuntimeError("DATABASE_URL is required for CONVERSATION_STORE_BACKEND=postgres")
            self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
            self._session_factory = sessionmaker(self._engine, expire_on_commit=False, future=True)
            if database_url.startswith("sqlite"):
                ConversationsBase.metadata.create_all(self._engine)

        def _session(self):
            return self._session_factory()

        def reset(self) -> None:
            with self._session() as session:
                with session.begin():
                    session.query(_WebhookDedupRow).delete()
                    session.query(_ConversationEventRow).delete()
                    session.query(_ConversationMessageRow).delete()
                    session.query(_ConversationThreadRow).delete()

        def register_webhook_receipt(self, *, source: str, receipt_key: str) -> bool:
            dedup_key = f"{source}:{receipt_key}"
            with self._session() as session:
                with session.begin():
                    row = session.get(_WebhookDedupRow, dedup_key)
                    if row is not None:
                        return True
                    session.add(
                        _WebhookDedupRow(
                            receipt_key=dedup_key,
                            source=source,
                            created_at=_now_utc(),
                        )
                    )
            return False

        def create_or_get_thread(
            self,
            *,
            channel: ContactChannel,
            external_contact: str,
            creator_id: str | None,
            creator_name: str | None,
            invoice_id: str | None,
            provider_thread_ref: str | None,
        ) -> ConversationThreadRecord:
            normalized_contact = _normalize_contact(channel, external_contact)
            with self._session() as session:
                with session.begin():
                    row = session.scalar(
                        select(_ConversationThreadRow)
                        .where(_ConversationThreadRow.channel == channel)
                        .where(_ConversationThreadRow.external_contact == normalized_contact)
                    )
                    if row is None:
                        now = _now_utc()
                        row = _ConversationThreadRow(
                            thread_id=f"cthread_{int(now.timestamp() * 1000)}",
                            channel=channel,
                            external_contact=normalized_contact,
                            creator_id=creator_id,
                            creator_name=creator_name,
                            invoice_id=invoice_id,
                            provider_thread_ref=provider_thread_ref,
                            status="open",
                            auto_reply_count=0,
                            last_message_preview=None,
                            last_inbound_at=None,
                            last_outbound_at=None,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(row)
                    else:
                        row.creator_id = row.creator_id or creator_id
                        row.creator_name = row.creator_name or creator_name
                        row.invoice_id = row.invoice_id or invoice_id
                        row.provider_thread_ref = row.provider_thread_ref or provider_thread_ref
                        row.updated_at = _now_utc()
                    session.flush()
                    return self._thread_record(row)

        def get_thread(self, thread_id: str) -> ConversationThreadRecord | None:
            with self._session() as session:
                row = session.get(_ConversationThreadRow, thread_id)
                return self._thread_record(row) if row is not None else None

        def list_threads(self, *, limit: int) -> list[ConversationThreadRecord]:
            with self._session() as session:
                rows = session.scalars(
                    select(_ConversationThreadRow)
                    .order_by(_ConversationThreadRow.updated_at.desc())
                    .limit(limit)
                ).all()
                return [self._thread_record(row) for row in rows]

        def list_messages(self, thread_id: str, *, limit: int) -> list[ConversationMessageRecord]:
            with self._session() as session:
                rows = session.scalars(
                    select(_ConversationMessageRow)
                    .where(_ConversationMessageRow.thread_id == thread_id)
                    .order_by(_ConversationMessageRow.created_at.asc())
                    .limit(limit)
                ).all()
                return [self._message_record(row) for row in rows]

        def append_message(
            self,
            *,
            thread_id: str,
            direction: ConversationDirection,
            sender_type: ConversationSenderType,
            body_text: str,
            delivery_state: str,
            provider_message_id: str | None,
            policy_reason: str | None,
        ) -> ConversationMessageRecord:
            now = _now_utc()
            with self._session() as session:
                with session.begin():
                    thread = session.get(_ConversationThreadRow, thread_id)
                    if thread is None:
                        raise KeyError(thread_id)
                    message = _ConversationMessageRow(
                        message_id=f"cmsg_{int(now.timestamp() * 1000000)}",
                        thread_id=thread_id,
                        direction=direction,
                        sender_type=sender_type,
                        body_text=body_text,
                        delivery_state=delivery_state,
                        provider_message_id=provider_message_id,
                        policy_reason=policy_reason,
                        created_at=now,
                    )
                    session.add(message)
                    thread.last_message_preview = _preview(body_text)
                    thread.updated_at = now
                    if direction == "inbound":
                        thread.last_inbound_at = now
                    else:
                        thread.last_outbound_at = now
                    session.flush()
                    return self._message_record(message)

        def append_event(self, *, thread_id: str, event_type: str, payload: dict[str, Any]) -> None:
            with self._session() as session:
                with session.begin():
                    session.add(
                        _ConversationEventRow(
                            thread_id=thread_id,
                            event_type=event_type,
                            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                            created_at=_now_utc(),
                        )
                    )

        def set_thread_status(self, *, thread_id: str, status: ConversationThreadStatus) -> ConversationThreadRecord:
            with self._session() as session:
                with session.begin():
                    thread = session.get(_ConversationThreadRow, thread_id)
                    if thread is None:
                        raise KeyError(thread_id)
                    thread.status = status
                    thread.updated_at = _now_utc()
                    session.flush()
                    return self._thread_record(thread)

        def increment_auto_reply_count(self, *, thread_id: str) -> ConversationThreadRecord:
            with self._session() as session:
                with session.begin():
                    thread = session.get(_ConversationThreadRow, thread_id)
                    if thread is None:
                        raise KeyError(thread_id)
                    thread.auto_reply_count += 1
                    thread.updated_at = _now_utc()
                    session.flush()
                    return self._thread_record(thread)

        def update_delivery_by_provider_message_id(self, *, provider_message_id: str, delivery_state: str) -> bool:
            with self._session() as session:
                with session.begin():
                    row = session.scalar(
                        select(_ConversationMessageRow).where(_ConversationMessageRow.provider_message_id == provider_message_id)
                    )
                    if row is None:
                        return False
                    row.delivery_state = delivery_state
                    return True

        def find_message_by_provider_message_id(self, provider_message_id: str) -> ConversationMessageRecord | None:
            with self._session() as session:
                row = session.scalar(
                    select(_ConversationMessageRow).where(_ConversationMessageRow.provider_message_id == provider_message_id)
                )
                return self._message_record(row) if row is not None else None

        @staticmethod
        def _thread_record(row: _ConversationThreadRow) -> ConversationThreadRecord:
            return ConversationThreadRecord(
                thread_id=row.thread_id,
                channel=row.channel,  # type: ignore[arg-type]
                external_contact=row.external_contact,
                creator_id=row.creator_id,
                creator_name=row.creator_name,
                invoice_id=row.invoice_id,
                provider_thread_ref=row.provider_thread_ref,
                status=row.status,  # type: ignore[arg-type]
                auto_reply_count=row.auto_reply_count,
                last_message_preview=row.last_message_preview,
                last_inbound_at=row.last_inbound_at,
                last_outbound_at=row.last_outbound_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

        @staticmethod
        def _message_record(row: _ConversationMessageRow) -> ConversationMessageRecord:
            return ConversationMessageRecord(
                message_id=row.message_id,
                thread_id=row.thread_id,
                direction=row.direction,  # type: ignore[arg-type]
                sender_type=row.sender_type,  # type: ignore[arg-type]
                body_text=row.body_text,
                delivery_state=row.delivery_state,
                provider_message_id=row.provider_message_id,
                policy_reason=row.policy_reason,
                created_at=row.created_at,
            )


else:
    ConversationsBase = None



def create_conversation_repository(*, backend: str, database_url: str) -> ConversationRepository:
    normalized = backend.strip().lower()
    if normalized == "postgres":
        if not SQLALCHEMY_AVAILABLE:
            raise RuntimeError("sqlalchemy is required for CONVERSATION_STORE_BACKEND=postgres")
        return SqlAlchemyConversationRepository(database_url)
    return InMemoryConversationRepository()


class ConversationService:
    def __init__(self, *, repository: ConversationRepository, store, settings) -> None:
        self._repository = repository
        self._store = store
        self._settings = settings

    def reset(self) -> None:
        self._repository.reset()

    def ingest_inbound(
        self,
        *,
        source: str,
        channel: ContactChannel,
        external_contact: str,
        body_text: str,
        provider_message_id: str,
        provider_thread_ref: str | None,
        sender: NotifierSender,
    ) -> ConversationInboundWebhookResponse:
        receipt_key = provider_message_id.strip()
        if not receipt_key:
            return ConversationInboundWebhookResponse(accepted=False, deduped=False, thread_id="unknown", message_id=None)

        deduped = self._repository.register_webhook_receipt(source=source, receipt_key=receipt_key)
        existing = self._repository.find_message_by_provider_message_id(receipt_key)
        if deduped and existing is not None:
            return ConversationInboundWebhookResponse(
                accepted=True,
                deduped=True,
                thread_id=existing.thread_id,
                message_id=existing.message_id,
            )

        creator_id = None
        creator_name = None
        invoice_id = None
        resolve = getattr(self._store, "resolve_conversation_context", None)
        if callable(resolve):
            creator_id, creator_name, invoice_id = resolve(channel=channel, external_contact=external_contact)

        thread = self._repository.create_or_get_thread(
            channel=channel,
            external_contact=external_contact,
            creator_id=creator_id,
            creator_name=creator_name,
            invoice_id=invoice_id,
            provider_thread_ref=provider_thread_ref,
        )
        inbound = self._repository.append_message(
            thread_id=thread.thread_id,
            direction="inbound",
            sender_type="creator",
            body_text=body_text,
            delivery_state="received",
            provider_message_id=provider_message_id,
            policy_reason=None,
        )
        self._repository.append_event(
            thread_id=thread.thread_id,
            event_type="inbound_received",
            payload={"source": source, "provider_message_id": provider_message_id},
        )

        if self._settings.conversation_enabled and self._settings.conversation_autoreply_enabled:
            decision = evaluate_conversation_policy(
                thread_status=thread.status,
                inbound_text=body_text,
                suggested_confidence=0.92,
                auto_reply_count=thread.auto_reply_count,
                confidence_threshold=self._settings.conversation_confidence_threshold,
                max_auto_replies=self._settings.conversation_max_auto_replies,
            )
            if decision.action == "handoff":
                self._repository.set_thread_status(thread_id=thread.thread_id, status="human_handoff")
                self._repository.append_event(
                    thread_id=thread.thread_id,
                    event_type="policy_handoff",
                    payload={"reason": decision.reason},
                )
            elif decision.action == "respond":
                self._send_reply(
                    thread_id=thread.thread_id,
                    reply_text=default_eros_reply(body_text),
                    sender_type="agent",
                    sender=sender,
                    policy_reason=decision.reason,
                )
                self._repository.increment_auto_reply_count(thread_id=thread.thread_id)

        return ConversationInboundWebhookResponse(
            accepted=True,
            deduped=False,
            thread_id=thread.thread_id,
            message_id=inbound.message_id,
        )

    def list_threads(self, *, limit: int = 100) -> ConversationThreadListResponse:
        threads = self._repository.list_threads(limit=limit)
        return ConversationThreadListResponse(items=[self._to_thread_item(value) for value in threads])

    def get_thread_detail(self, thread_id: str) -> ConversationThreadDetailResponse:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise KeyError(thread_id)
        messages = self._repository.list_messages(thread_id, limit=500)
        return ConversationThreadDetailResponse(
            thread=self._to_thread_item(thread),
            messages=[self._to_message_item(value) for value in messages],
        )

    def handoff_thread(self, thread_id: str, *, reason: str | None) -> ConversationHandoffResponse:
        thread = self._repository.set_thread_status(thread_id=thread_id, status="human_handoff")
        self._repository.append_event(
            thread_id=thread_id,
            event_type="admin_handoff",
            payload={"reason": reason},
        )
        return ConversationHandoffResponse(thread_id=thread_id, status=thread.status, updated_at=thread.updated_at)

    def send_manual_reply(self, thread_id: str, *, body_text: str, sender: NotifierSender) -> ConversationReplyResponse:
        return self._send_reply(
            thread_id=thread_id,
            reply_text=body_text,
            sender_type="admin",
            sender=sender,
            policy_reason="manual_reply",
        )

    def evaluate_agent_suggestion(self, *, thread_id: str, reply_text: str, confidence: float) -> AgentConversationSuggestResponse:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise KeyError(thread_id)
        latest_messages = self._repository.list_messages(thread_id, limit=1)
        inbound_text = latest_messages[-1].body_text if latest_messages else ""
        decision = evaluate_conversation_policy(
            thread_status=thread.status,
            inbound_text=inbound_text,
            suggested_confidence=confidence,
            auto_reply_count=thread.auto_reply_count,
            confidence_threshold=self._settings.conversation_confidence_threshold,
            max_auto_replies=self._settings.conversation_max_auto_replies,
        )
        return AgentConversationSuggestResponse(
            action=decision.action,
            approved=decision.action == "respond",
            policy_reason=decision.reason,
            confidence=confidence,
        )

    def execute_agent_action(
        self,
        *,
        thread_id: str,
        action: str,
        reply_text: str | None,
        confidence: float,
        sender: NotifierSender,
    ) -> AgentConversationExecuteResponse:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise KeyError(thread_id)

        if action == "handoff":
            self._repository.set_thread_status(thread_id=thread_id, status="human_handoff")
            self._repository.append_event(thread_id=thread_id, event_type="agent_handoff", payload={"confidence": confidence})
            return AgentConversationExecuteResponse(thread_id=thread_id, action="handoff", status="ok", policy_reason="agent_handoff")

        if action == "no_reply":
            self._repository.append_event(thread_id=thread_id, event_type="agent_no_reply", payload={"confidence": confidence})
            return AgentConversationExecuteResponse(thread_id=thread_id, action="no_reply", status="ok", policy_reason="agent_no_reply")

        if action != "send_reply":
            return AgentConversationExecuteResponse(thread_id=thread_id, action="no_reply", status="invalid_action")

        if not self._settings.conversation_autoreply_enabled:
            return AgentConversationExecuteResponse(
                thread_id=thread_id,
                action="send_reply",
                status="blocked",
                policy_reason="conversation_autoreply_disabled",
            )

        if not reply_text:
            return AgentConversationExecuteResponse(thread_id=thread_id, action="send_reply", status="blocked", policy_reason="reply_text_required")

        decision = self.evaluate_agent_suggestion(thread_id=thread_id, reply_text=reply_text, confidence=confidence)
        if not decision.approved:
            if decision.action == "handoff":
                self._repository.set_thread_status(thread_id=thread_id, status="human_handoff")
            return AgentConversationExecuteResponse(
                thread_id=thread_id,
                action="send_reply",
                status="blocked",
                policy_reason=decision.policy_reason,
            )

        reply = self._send_reply(
            thread_id=thread_id,
            reply_text=reply_text,
            sender_type="agent",
            sender=sender,
            policy_reason=decision.policy_reason,
        )
        self._repository.increment_auto_reply_count(thread_id=thread_id)
        return AgentConversationExecuteResponse(
            thread_id=thread_id,
            action="send_reply",
            status="ok",
            message_id=reply.message_id,
            policy_reason=decision.policy_reason,
        )

    def update_delivery_status(self, *, provider_message_id: str, delivery_state: str) -> bool:
        return self._repository.update_delivery_by_provider_message_id(
            provider_message_id=provider_message_id,
            delivery_state=delivery_state,
        )

    def _send_reply(
        self,
        *,
        thread_id: str,
        reply_text: str,
        sender_type: ConversationSenderType,
        sender: NotifierSender,
        policy_reason: str,
    ) -> ConversationReplyResponse:
        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise KeyError(thread_id)

        request = ProviderConversationRequest(
            thread_id=thread.thread_id,
            contact_channel=thread.channel,
            contact_target=thread.external_contact,
            message=reply_text,
        )
        provider_result = sender.send_message(request, dry_run=False)
        delivery_state = "sent" if provider_result.status == "sent" else "failed"
        message = self._repository.append_message(
            thread_id=thread_id,
            direction="outbound",
            sender_type=sender_type,
            body_text=reply_text,
            delivery_state=delivery_state,
            provider_message_id=provider_result.provider_message_id,
            policy_reason=policy_reason,
        )
        self._repository.append_event(
            thread_id=thread_id,
            event_type="reply_sent" if delivery_state == "sent" else "reply_failed",
            payload={
                "sender_type": sender_type,
                "delivery_state": delivery_state,
                "error_code": provider_result.error_code,
            },
        )
        return ConversationReplyResponse(
            thread_id=thread_id,
            message_id=message.message_id,
            delivery_state=delivery_state,  # type: ignore[arg-type]
            provider_message_id=provider_result.provider_message_id,
        )

    def _to_thread_item(self, record: ConversationThreadRecord) -> ConversationThreadItem:
        return ConversationThreadItem(
            thread_id=record.thread_id,
            channel=record.channel,
            external_contact_masked=mask_contact_target(record.external_contact, record.channel),
            creator_id=record.creator_id,
            creator_name=record.creator_name,
            invoice_id=record.invoice_id,
            status=record.status,
            auto_reply_count=record.auto_reply_count,
            last_message_preview=record.last_message_preview,
            last_inbound_at=record.last_inbound_at,
            last_outbound_at=record.last_outbound_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_message_item(record: ConversationMessageRecord) -> ConversationMessageItem:
        return ConversationMessageItem(
            message_id=record.message_id,
            direction=record.direction,
            sender_type=record.sender_type,
            body_text=record.body_text,
            delivery_state=record.delivery_state,  # type: ignore[arg-type]
            provider_message_id=record.provider_message_id,
            policy_reason=record.policy_reason,
            created_at=record.created_at,
        )
