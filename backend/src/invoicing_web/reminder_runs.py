from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .models import (
    ReminderChannelResult,
    ReminderEvaluateRequest,
    ReminderResult,
    ReminderRunRequest,
    ReminderRunResponse,
)
from .notifier import NotifierSender
from .store import PlannedReminderAttempt, PlannedReminderRun

MAX_OUTBOX_RETRIES = 5
BASE_RETRY_SECONDS = 15


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload_hash(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _stable_response_hashable(response: ReminderRunResponse) -> str:
    return json.dumps(response.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ReminderIdempotencyRecord:
    idempotency_key: str
    request_hash: str
    response_payload: str
    run_id: str
    created_at: datetime


@dataclass(frozen=True)
class ReminderRunRecord:
    run_id: str
    mode: str
    dry_run: bool
    triggered_by_type: str
    triggered_by_id: str
    request_hash: str
    idempotency_key: str | None
    run_at: datetime
    status: str
    evaluated_count: int
    eligible_count: int
    sent_count: int
    failed_count: int
    skipped_count: int
    escalated_count: int
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class ReminderAttemptRecord:
    attempt_id: int
    run_id: str
    invoice_id: str
    dispatch_id: str | None
    eligible: bool
    reason: str
    status: str
    next_eligible_at: datetime | None
    contact_target_masked: str | None
    planned_channel_count: int
    attempted_at: datetime | None
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    channel_results_json: str
    created_at: datetime


@dataclass(frozen=True)
class OutboxMessageRecord:
    outbox_id: int
    run_id: str
    attempt_id: int
    invoice_id: str
    channel: str
    recipient: str
    payload_json: str
    status: str
    tries: int
    available_at: datetime
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ReminderRunRepository(Protocol):
    def reset(self) -> None: ...

    def get_idempotency(self, idempotency_key: str) -> ReminderIdempotencyRecord | None: ...

    def save_idempotency(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        response_payload: str,
        run_id: str,
    ) -> None: ...

    def create_planned_run(
        self,
        *,
        mode: str,
        dry_run: bool,
        triggered_by_type: str,
        triggered_by_id: str,
        request_hash: str,
        idempotency_key: str | None,
        request_payload: dict[str, object],
        plan: PlannedReminderRun,
        create_outbox: bool,
    ) -> str: ...

    def get_run(self, run_id: str) -> ReminderRunRecord | None: ...
    def get_latest_run(self) -> ReminderRunRecord | None: ...

    def list_attempts(self, run_id: str) -> list[ReminderAttemptRecord]: ...

    def list_outbox_messages(self, run_id: str) -> list[OutboxMessageRecord]: ...

    def claim_available_outbox(self, run_id: str, *, max_messages: int, now: datetime) -> list[OutboxMessageRecord]: ...

    def mark_outbox_sent(self, outbox_id: int, *, provider_message_id: str | None) -> None: ...

    def mark_outbox_retry(self, outbox_id: int, *, error_code: str | None, error_message: str | None, now: datetime) -> None: ...

    def mark_outbox_dead_letter(self, outbox_id: int, *, error_code: str | None, error_message: str | None) -> None: ...

    def update_attempt_result(
        self,
        attempt_id: int,
        *,
        status: str,
        reason: str,
        attempted_at: datetime | None,
        provider_message_id: str | None,
        error_code: str | None,
        error_message: str | None,
        channel_results: list[dict[str, object]],
    ) -> None: ...

    def finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        sent_count: int,
        failed_count: int,
        skipped_count: int,
        escalated_count: int,
        finished_at: datetime,
    ) -> None: ...


class InMemoryReminderRunRepository:
    def __init__(self) -> None:
        self._run_counter = 1
        self._attempt_counter = 1
        self._outbox_counter = 1
        self._runs: dict[str, ReminderRunRecord] = {}
        self._attempts: dict[int, ReminderAttemptRecord] = {}
        self._attempt_ids_by_run: dict[str, list[int]] = {}
        self._outbox: dict[int, OutboxMessageRecord] = {}
        self._outbox_ids_by_run: dict[str, list[int]] = {}
        self._idempotency: dict[str, ReminderIdempotencyRecord] = {}

    def reset(self) -> None:
        self._run_counter = 1
        self._attempt_counter = 1
        self._outbox_counter = 1
        self._runs.clear()
        self._attempts.clear()
        self._attempt_ids_by_run.clear()
        self._outbox.clear()
        self._outbox_ids_by_run.clear()
        self._idempotency.clear()

    def get_idempotency(self, idempotency_key: str) -> ReminderIdempotencyRecord | None:
        return self._idempotency.get(idempotency_key)

    def save_idempotency(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        response_payload: str,
        run_id: str,
    ) -> None:
        self._idempotency[idempotency_key] = ReminderIdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_payload=response_payload,
            run_id=run_id,
            created_at=_now_utc(),
        )

    def create_planned_run(
        self,
        *,
        mode: str,
        dry_run: bool,
        triggered_by_type: str,
        triggered_by_id: str,
        request_hash: str,
        idempotency_key: str | None,
        request_payload: dict[str, object],
        plan: PlannedReminderRun,
        create_outbox: bool,
    ) -> str:
        _ = request_payload
        run_id = f"rrun_{self._run_counter:06d}"
        self._run_counter += 1
        run = ReminderRunRecord(
            run_id=run_id,
            mode=mode,
            dry_run=dry_run,
            triggered_by_type=triggered_by_type,
            triggered_by_id=triggered_by_id,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            run_at=plan.run_at,
            status="planned",
            evaluated_count=plan.evaluated_count,
            eligible_count=plan.eligible_count,
            sent_count=0,
            failed_count=0,
            skipped_count=plan.skipped_count,
            escalated_count=plan.escalated_count,
            created_at=_now_utc(),
            finished_at=None,
        )
        self._runs[run_id] = run
        self._attempt_ids_by_run[run_id] = []
        self._outbox_ids_by_run[run_id] = []

        for planned_attempt in plan.attempts:
            attempt_id = self._attempt_counter
            self._attempt_counter += 1
            attempt = ReminderAttemptRecord(
                attempt_id=attempt_id,
                run_id=run_id,
                invoice_id=planned_attempt.invoice_id,
                dispatch_id=planned_attempt.dispatch_id,
                eligible=planned_attempt.eligible,
                reason=planned_attempt.reason,
                status="planned" if planned_attempt.eligible else "skipped",
                next_eligible_at=planned_attempt.next_eligible_at,
                contact_target_masked=planned_attempt.contact_target_masked,
                planned_channel_count=len(planned_attempt.channels),
                attempted_at=None,
                provider_message_id=None,
                error_code=None,
                error_message=None,
                channel_results_json="[]",
                created_at=_now_utc(),
            )
            self._attempts[attempt_id] = attempt
            self._attempt_ids_by_run[run_id].append(attempt_id)

            if not create_outbox or dry_run or (not planned_attempt.eligible):
                continue
            for planned_channel in planned_attempt.channels:
                outbox_id = self._outbox_counter
                self._outbox_counter += 1
                outbox = OutboxMessageRecord(
                    outbox_id=outbox_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    invoice_id=planned_attempt.invoice_id,
                    channel=planned_channel.channel,
                    recipient=planned_channel.recipient,
                    payload_json=json.dumps(
                        {
                            "invoice_id": planned_channel.payload.invoice_id,
                            "creator_id": planned_channel.payload.creator_id,
                            "creator_name": planned_channel.payload.creator_name,
                            "contact_channel": planned_channel.payload.contact_channel,
                            "contact_target": planned_channel.payload.contact_target,
                            "currency": planned_channel.payload.currency,
                            "amount_due": planned_channel.payload.amount_due,
                            "balance_due": planned_channel.payload.balance_due,
                            "due_date": planned_channel.payload.due_date.isoformat(),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    status="pending",
                    tries=0,
                    available_at=plan.run_at,
                    provider_message_id=None,
                    error_code=None,
                    error_message=None,
                    created_at=_now_utc(),
                    updated_at=_now_utc(),
                )
                self._outbox[outbox_id] = outbox
                self._outbox_ids_by_run[run_id].append(outbox_id)

        return run_id

    def get_run(self, run_id: str) -> ReminderRunRecord | None:
        return self._runs.get(run_id)

    def get_latest_run(self) -> ReminderRunRecord | None:
        if not self._runs:
            return None
        return max(self._runs.values(), key=lambda value: (value.run_at, value.created_at))

    def list_attempts(self, run_id: str) -> list[ReminderAttemptRecord]:
        ids = self._attempt_ids_by_run.get(run_id, [])
        return [self._attempts[value] for value in ids]

    def list_outbox_messages(self, run_id: str) -> list[OutboxMessageRecord]:
        ids = self._outbox_ids_by_run.get(run_id, [])
        return [self._outbox[value] for value in ids]

    def claim_available_outbox(self, run_id: str, *, max_messages: int, now: datetime) -> list[OutboxMessageRecord]:
        claimed: list[OutboxMessageRecord] = []
        for outbox_id in self._outbox_ids_by_run.get(run_id, []):
            row = self._outbox[outbox_id]
            if row.status != "pending":
                continue
            if row.available_at > now:
                continue
            if len(claimed) >= max_messages:
                break
            updated = OutboxMessageRecord(
                **{**row.__dict__, "status": "processing", "updated_at": _now_utc()}
            )
            self._outbox[outbox_id] = updated
            claimed.append(updated)
        return claimed

    def mark_outbox_sent(self, outbox_id: int, *, provider_message_id: str | None) -> None:
        row = self._outbox[outbox_id]
        self._outbox[outbox_id] = OutboxMessageRecord(
            **{
                **row.__dict__,
                "status": "sent",
                "provider_message_id": provider_message_id,
                "updated_at": _now_utc(),
            }
        )

    def mark_outbox_retry(self, outbox_id: int, *, error_code: str | None, error_message: str | None, now: datetime) -> None:
        row = self._outbox[outbox_id]
        next_tries = row.tries + 1
        backoff_seconds = min(BASE_RETRY_SECONDS * (2 ** max(0, next_tries - 1)), 600)
        self._outbox[outbox_id] = OutboxMessageRecord(
            **{
                **row.__dict__,
                "status": "pending",
                "tries": next_tries,
                "available_at": now + timedelta(seconds=backoff_seconds),
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": _now_utc(),
            }
        )

    def mark_outbox_dead_letter(self, outbox_id: int, *, error_code: str | None, error_message: str | None) -> None:
        row = self._outbox[outbox_id]
        self._outbox[outbox_id] = OutboxMessageRecord(
            **{
                **row.__dict__,
                "status": "dead_letter",
                "tries": row.tries + 1,
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": _now_utc(),
            }
        )

    def update_attempt_result(
        self,
        attempt_id: int,
        *,
        status: str,
        reason: str,
        attempted_at: datetime | None,
        provider_message_id: str | None,
        error_code: str | None,
        error_message: str | None,
        channel_results: list[dict[str, object]],
    ) -> None:
        row = self._attempts[attempt_id]
        self._attempts[attempt_id] = ReminderAttemptRecord(
            **{
                **row.__dict__,
                "status": status,
                "reason": reason,
                "attempted_at": attempted_at,
                "provider_message_id": provider_message_id,
                "error_code": error_code,
                "error_message": error_message,
                "channel_results_json": json.dumps(channel_results, sort_keys=True, separators=(",", ":")),
            }
        )

    def finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        sent_count: int,
        failed_count: int,
        skipped_count: int,
        escalated_count: int,
        finished_at: datetime,
    ) -> None:
        row = self._runs[run_id]
        self._runs[run_id] = ReminderRunRecord(
            **{
                **row.__dict__,
                "status": status,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "escalated_count": escalated_count,
                "finished_at": finished_at,
            }
        )


SQLALCHEMY_AVAILABLE = True
try:
    from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
except ModuleNotFoundError:
    SQLALCHEMY_AVAILABLE = False


if SQLALCHEMY_AVAILABLE:

    class ReminderRunsBase(DeclarativeBase):
        pass


    class _ReminderRunRow(ReminderRunsBase):
        __tablename__ = "reminder_runs"

        run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        mode: Mapped[str] = mapped_column(String(32), nullable=False)
        dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
        triggered_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
        triggered_by_id: Mapped[str] = mapped_column(String(128), nullable=False)
        request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
        idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
        request_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
        run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        status: Mapped[str] = mapped_column(String(32), nullable=False)
        evaluated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        escalated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


    class _ReminderAttemptRow(ReminderRunsBase):
        __tablename__ = "reminder_attempts"

        attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        run_id: Mapped[str] = mapped_column(String(64), ForeignKey("reminder_runs.run_id"), nullable=False, index=True)
        invoice_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
        dispatch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
        eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
        reason: Mapped[str] = mapped_column(String(64), nullable=False)
        status: Mapped[str] = mapped_column(String(32), nullable=False)
        next_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        contact_target_masked: Mapped[str | None] = mapped_column(String(256), nullable=True)
        planned_channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        provider_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
        error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
        error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
        channel_results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class _ReminderOutboxRow(ReminderRunsBase):
        __tablename__ = "reminder_outbox_messages"

        outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        run_id: Mapped[str] = mapped_column(String(64), ForeignKey("reminder_runs.run_id"), nullable=False, index=True)
        attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("reminder_attempts.attempt_id"), nullable=False, index=True)
        invoice_id: Mapped[str] = mapped_column(String(128), nullable=False)
        channel: Mapped[str] = mapped_column(String(16), nullable=False)
        recipient: Mapped[str] = mapped_column(String(256), nullable=False)
        payload_json: Mapped[str] = mapped_column(Text, nullable=False)
        status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
        tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
        provider_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
        error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
        error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class _ReminderIdempotencyRow(ReminderRunsBase):
        __tablename__ = "reminder_idempotency_keys"

        idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
        request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
        run_id: Mapped[str] = mapped_column(String(64), ForeignKey("reminder_runs.run_id"), nullable=False)
        response_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
else:
    ReminderRunsBase = None


class SqlAlchemyReminderRunRepository:
    def __init__(self, database_url: str) -> None:
        if not SQLALCHEMY_AVAILABLE:
            raise RuntimeError("sqlalchemy is required for REMINDER_STORE_BACKEND=postgres")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for REMINDER_STORE_BACKEND=postgres")
        self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, future=True)
        if database_url.startswith("sqlite"):
            ReminderRunsBase.metadata.create_all(self._engine)

    def _session(self):
        return self._session_factory()

    def reset(self) -> None:
        with self._session() as session:
            with session.begin():
                session.query(_ReminderIdempotencyRow).delete()
                session.query(_ReminderOutboxRow).delete()
                session.query(_ReminderAttemptRow).delete()
                session.query(_ReminderRunRow).delete()

    def get_idempotency(self, idempotency_key: str) -> ReminderIdempotencyRecord | None:
        with self._session() as session:
            row = session.get(_ReminderIdempotencyRow, idempotency_key)
            if row is None:
                return None
            return ReminderIdempotencyRecord(
                idempotency_key=row.idempotency_key,
                request_hash=row.request_hash,
                response_payload=row.response_payload_json,
                run_id=row.run_id,
                created_at=_coerce_utc(row.created_at),
            )

    def save_idempotency(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        response_payload: str,
        run_id: str,
    ) -> None:
        with self._session() as session:
            with session.begin():
                existing = session.get(_ReminderIdempotencyRow, idempotency_key)
                if existing is None:
                    session.add(
                        _ReminderIdempotencyRow(
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            run_id=run_id,
                            response_payload_json=response_payload,
                            created_at=_now_utc(),
                        )
                    )
                else:
                    existing.request_hash = request_hash
                    existing.run_id = run_id
                    existing.response_payload_json = response_payload

    def create_planned_run(
        self,
        *,
        mode: str,
        dry_run: bool,
        triggered_by_type: str,
        triggered_by_id: str,
        request_hash: str,
        idempotency_key: str | None,
        request_payload: dict[str, object],
        plan: PlannedReminderRun,
        create_outbox: bool,
    ) -> str:
        run_id = f"rrun_{secrets.token_hex(8)}"
        with self._session() as session:
            with session.begin():
                session.add(
                    _ReminderRunRow(
                        run_id=run_id,
                        mode=mode,
                        dry_run=dry_run,
                        triggered_by_type=triggered_by_type,
                        triggered_by_id=triggered_by_id,
                        request_hash=request_hash,
                        idempotency_key=idempotency_key,
                        request_payload_json=json.dumps(request_payload, sort_keys=True, separators=(",", ":")),
                        run_at=plan.run_at,
                        status="planned",
                        evaluated_count=plan.evaluated_count,
                        eligible_count=plan.eligible_count,
                        sent_count=0,
                        failed_count=0,
                        skipped_count=plan.skipped_count,
                        escalated_count=plan.escalated_count,
                        created_at=_now_utc(),
                    )
                )

                for planned_attempt in plan.attempts:
                    attempt = _ReminderAttemptRow(
                        run_id=run_id,
                        invoice_id=planned_attempt.invoice_id,
                        dispatch_id=planned_attempt.dispatch_id,
                        eligible=planned_attempt.eligible,
                        reason=planned_attempt.reason,
                        status="planned" if planned_attempt.eligible else "skipped",
                        next_eligible_at=planned_attempt.next_eligible_at,
                        contact_target_masked=planned_attempt.contact_target_masked,
                        planned_channel_count=len(planned_attempt.channels),
                        attempted_at=None,
                        provider_message_id=None,
                        error_code=None,
                        error_message=None,
                        channel_results_json="[]",
                        created_at=_now_utc(),
                    )
                    session.add(attempt)
                    session.flush()

                    if not create_outbox or dry_run or (not planned_attempt.eligible):
                        continue
                    for planned_channel in planned_attempt.channels:
                        session.add(
                            _ReminderOutboxRow(
                                run_id=run_id,
                                attempt_id=attempt.attempt_id,
                                invoice_id=planned_attempt.invoice_id,
                                channel=planned_channel.channel,
                                recipient=planned_channel.recipient,
                                payload_json=json.dumps(
                                    {
                                        "invoice_id": planned_channel.payload.invoice_id,
                                        "creator_id": planned_channel.payload.creator_id,
                                        "creator_name": planned_channel.payload.creator_name,
                                        "contact_channel": planned_channel.payload.contact_channel,
                                        "contact_target": planned_channel.payload.contact_target,
                                        "currency": planned_channel.payload.currency,
                                        "amount_due": planned_channel.payload.amount_due,
                                        "balance_due": planned_channel.payload.balance_due,
                                        "due_date": planned_channel.payload.due_date.isoformat(),
                                    },
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                                status="pending",
                                tries=0,
                                available_at=plan.run_at,
                                provider_message_id=None,
                                error_code=None,
                                error_message=None,
                                created_at=_now_utc(),
                                updated_at=_now_utc(),
                            )
                        )
        return run_id

    def get_run(self, run_id: str) -> ReminderRunRecord | None:
        with self._session() as session:
            row = session.get(_ReminderRunRow, run_id)
            if row is None:
                return None
            return ReminderRunRecord(
                run_id=row.run_id,
                mode=row.mode,
                dry_run=row.dry_run,
                triggered_by_type=row.triggered_by_type,
                triggered_by_id=row.triggered_by_id,
                request_hash=row.request_hash,
                idempotency_key=row.idempotency_key,
                run_at=_coerce_utc(row.run_at),
                status=row.status,
                evaluated_count=row.evaluated_count,
                eligible_count=row.eligible_count,
                sent_count=row.sent_count,
                failed_count=row.failed_count,
                skipped_count=row.skipped_count,
                escalated_count=row.escalated_count,
                created_at=_coerce_utc(row.created_at),
                finished_at=_coerce_utc(row.finished_at) if row.finished_at is not None else None,
            )

    def get_latest_run(self) -> ReminderRunRecord | None:
        with self._session() as session:
            row = session.execute(
                select(_ReminderRunRow)
                .order_by(_ReminderRunRow.run_at.desc(), _ReminderRunRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            return ReminderRunRecord(
                run_id=row.run_id,
                mode=row.mode,
                dry_run=row.dry_run,
                triggered_by_type=row.triggered_by_type,
                triggered_by_id=row.triggered_by_id,
                request_hash=row.request_hash,
                idempotency_key=row.idempotency_key,
                run_at=_coerce_utc(row.run_at),
                status=row.status,
                evaluated_count=row.evaluated_count,
                eligible_count=row.eligible_count,
                sent_count=row.sent_count,
                failed_count=row.failed_count,
                skipped_count=row.skipped_count,
                escalated_count=row.escalated_count,
                created_at=_coerce_utc(row.created_at),
                finished_at=_coerce_utc(row.finished_at) if row.finished_at is not None else None,
            )

    def list_attempts(self, run_id: str) -> list[ReminderAttemptRecord]:
        with self._session() as session:
            rows = session.execute(
                select(_ReminderAttemptRow)
                .where(_ReminderAttemptRow.run_id == run_id)
                .order_by(_ReminderAttemptRow.attempt_id.asc())
            ).scalars()
            result: list[ReminderAttemptRecord] = []
            for row in rows:
                result.append(
                    ReminderAttemptRecord(
                        attempt_id=row.attempt_id,
                        run_id=row.run_id,
                        invoice_id=row.invoice_id,
                        dispatch_id=row.dispatch_id,
                        eligible=row.eligible,
                        reason=row.reason,
                        status=row.status,
                        next_eligible_at=_coerce_utc(row.next_eligible_at) if row.next_eligible_at is not None else None,
                        contact_target_masked=row.contact_target_masked,
                        planned_channel_count=row.planned_channel_count,
                        attempted_at=_coerce_utc(row.attempted_at) if row.attempted_at is not None else None,
                        provider_message_id=row.provider_message_id,
                        error_code=row.error_code,
                        error_message=row.error_message,
                        channel_results_json=row.channel_results_json,
                        created_at=_coerce_utc(row.created_at),
                    )
                )
            return result

    def list_outbox_messages(self, run_id: str) -> list[OutboxMessageRecord]:
        with self._session() as session:
            rows = session.execute(
                select(_ReminderOutboxRow)
                .where(_ReminderOutboxRow.run_id == run_id)
                .order_by(_ReminderOutboxRow.outbox_id.asc())
            ).scalars()
            result: list[OutboxMessageRecord] = []
            for row in rows:
                result.append(
                    OutboxMessageRecord(
                        outbox_id=row.outbox_id,
                        run_id=row.run_id,
                        attempt_id=row.attempt_id,
                        invoice_id=row.invoice_id,
                        channel=row.channel,
                        recipient=row.recipient,
                        payload_json=row.payload_json,
                        status=row.status,
                        tries=row.tries,
                        available_at=_coerce_utc(row.available_at),
                        provider_message_id=row.provider_message_id,
                        error_code=row.error_code,
                        error_message=row.error_message,
                        created_at=_coerce_utc(row.created_at),
                        updated_at=_coerce_utc(row.updated_at),
                    )
                )
            return result

    def claim_available_outbox(self, run_id: str, *, max_messages: int, now: datetime) -> list[OutboxMessageRecord]:
        normalized_now = _coerce_utc(now)
        with self._session() as session:
            with session.begin():
                query = (
                    select(_ReminderOutboxRow)
                    .where(_ReminderOutboxRow.run_id == run_id)
                    .where(_ReminderOutboxRow.status == "pending")
                    .where(_ReminderOutboxRow.available_at <= normalized_now)
                    .order_by(_ReminderOutboxRow.outbox_id.asc())
                    .limit(max_messages)
                )
                rows = session.execute(query).scalars().all()
                claimed: list[OutboxMessageRecord] = []
                for row in rows:
                    row.status = "processing"
                    row.updated_at = _now_utc()
                    claimed.append(
                        OutboxMessageRecord(
                            outbox_id=row.outbox_id,
                            run_id=row.run_id,
                            attempt_id=row.attempt_id,
                            invoice_id=row.invoice_id,
                            channel=row.channel,
                            recipient=row.recipient,
                            payload_json=row.payload_json,
                            status=row.status,
                            tries=row.tries,
                            available_at=_coerce_utc(row.available_at),
                            provider_message_id=row.provider_message_id,
                            error_code=row.error_code,
                            error_message=row.error_message,
                            created_at=_coerce_utc(row.created_at),
                            updated_at=_coerce_utc(row.updated_at),
                        )
                    )
                return claimed

    def mark_outbox_sent(self, outbox_id: int, *, provider_message_id: str | None) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(_ReminderOutboxRow, outbox_id)
                if row is None:
                    return
                row.status = "sent"
                row.provider_message_id = provider_message_id
                row.updated_at = _now_utc()

    def mark_outbox_retry(self, outbox_id: int, *, error_code: str | None, error_message: str | None, now: datetime) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(_ReminderOutboxRow, outbox_id)
                if row is None:
                    return
                next_tries = row.tries + 1
                backoff_seconds = min(BASE_RETRY_SECONDS * (2 ** max(0, next_tries - 1)), 600)
                row.status = "pending"
                row.tries = next_tries
                row.available_at = _coerce_utc(now) + timedelta(seconds=backoff_seconds)
                row.error_code = error_code
                row.error_message = error_message
                row.updated_at = _now_utc()

    def mark_outbox_dead_letter(self, outbox_id: int, *, error_code: str | None, error_message: str | None) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(_ReminderOutboxRow, outbox_id)
                if row is None:
                    return
                row.status = "dead_letter"
                row.tries = row.tries + 1
                row.error_code = error_code
                row.error_message = error_message
                row.updated_at = _now_utc()

    def update_attempt_result(
        self,
        attempt_id: int,
        *,
        status: str,
        reason: str,
        attempted_at: datetime | None,
        provider_message_id: str | None,
        error_code: str | None,
        error_message: str | None,
        channel_results: list[dict[str, object]],
    ) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(_ReminderAttemptRow, attempt_id)
                if row is None:
                    return
                row.status = status
                row.reason = reason
                row.attempted_at = attempted_at
                row.provider_message_id = provider_message_id
                row.error_code = error_code
                row.error_message = error_message
                row.channel_results_json = json.dumps(channel_results, sort_keys=True, separators=(",", ":"))

    def finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        sent_count: int,
        failed_count: int,
        skipped_count: int,
        escalated_count: int,
        finished_at: datetime,
    ) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(_ReminderRunRow, run_id)
                if row is None:
                    return
                row.status = status
                row.sent_count = sent_count
                row.failed_count = failed_count
                row.skipped_count = skipped_count
                row.escalated_count = escalated_count
                row.finished_at = _coerce_utc(finished_at)


def create_reminder_run_repository(*, backend: str, database_url: str) -> ReminderRunRepository:
    normalized = backend.strip().lower()
    if normalized == "postgres":
        return SqlAlchemyReminderRunRepository(database_url)
    return InMemoryReminderRunRepository()


class ReminderWorkflowService:
    def __init__(self, *, repository: ReminderRunRepository, store) -> None:
        self._repository = repository
        self._store = store

    def run_once(
        self,
        payload: ReminderRunRequest,
        *,
        sender: NotifierSender,
        actor_type: str,
        actor_id: str,
    ) -> ReminderRunResponse:
        request_payload = payload.model_dump(mode="json")
        request_hash = _payload_hash(request_payload)

        if payload.idempotency_key:
            existing = self._repository.get_idempotency(payload.idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("idempotency_key already used with a different request payload")
                parsed = ReminderRunResponse.model_validate_json(existing.response_payload)
                return parsed

        plan = self._store.plan_reminders(now_override=payload.now_override, limit=payload.limit)
        run_id = self._repository.create_planned_run(
            mode="run_once",
            dry_run=payload.dry_run,
            triggered_by_type=actor_type,
            triggered_by_id=actor_id,
            request_hash=request_hash,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            plan=plan,
            create_outbox=True,
        )

        if payload.dry_run:
            response = self._build_dry_response(run_id, plan, payload.idempotency_key)
            self._repository.finalize_run(
                run_id,
                status="completed",
                sent_count=0,
                failed_count=0,
                skipped_count=response.skipped_count,
                escalated_count=response.escalated_count,
                finished_at=plan.run_at,
            )
            if payload.idempotency_key:
                self._repository.save_idempotency(
                    idempotency_key=payload.idempotency_key,
                    request_hash=request_hash,
                    response_payload=_stable_response_hashable(response),
                    run_id=run_id,
                )
            return response

        response = self.send_run(run_id, sender=sender, max_messages=None)
        if payload.idempotency_key:
            self._repository.save_idempotency(
                idempotency_key=payload.idempotency_key,
                request_hash=request_hash,
                response_payload=_stable_response_hashable(response),
                run_id=run_id,
            )
        return response

    def evaluate(
        self,
        payload: ReminderEvaluateRequest,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ReminderRunResponse:
        request_payload = payload.model_dump(mode="json")
        request_hash = _payload_hash(request_payload)
        plan = self._store.plan_reminders(now_override=payload.now_override, limit=payload.limit)
        run_id = self._repository.create_planned_run(
            mode="evaluate",
            dry_run=False,
            triggered_by_type=actor_type,
            triggered_by_id=actor_id,
            request_hash=request_hash,
            idempotency_key=payload.idempotency_key,
            request_payload=request_payload,
            plan=plan,
            create_outbox=True,
        )
        response = self._build_dry_response(run_id, plan, payload.idempotency_key)
        self._repository.finalize_run(
            run_id,
            status="planned",
            sent_count=0,
            failed_count=0,
            skipped_count=response.skipped_count,
            escalated_count=response.escalated_count,
            finished_at=plan.run_at,
        )
        return response

    def send_run(self, run_id: str, *, sender: NotifierSender, max_messages: int | None) -> ReminderRunResponse:
        run = self._repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)

        budget = max_messages or 1000
        processed = 0
        while processed < budget:
            current_now = _now_utc()
            claim_cutoff = current_now if current_now > run.run_at else run.run_at
            chunk = self._repository.claim_available_outbox(
                run_id,
                max_messages=min(100, budget - processed),
                now=claim_cutoff,
            )
            if not chunk:
                break
            for message in chunk:
                processed += 1
                payload = json.loads(message.payload_json)
                recipient = str(payload.get("contact_target") or "")
                if not recipient:
                    self._repository.mark_outbox_dead_letter(
                        message.outbox_id,
                        error_code="recipient_missing",
                        error_message=f"Recipient missing for channel {message.channel}",
                    )
                    continue

                provider_payload = self._decode_provider_payload(payload)
                provider_result = sender.send_friendly_reminder(provider_payload, dry_run=False)
                if provider_result.status == "sent":
                    self._repository.mark_outbox_sent(
                        message.outbox_id,
                        provider_message_id=provider_result.provider_message_id,
                    )
                    continue

                # failed or dry_run in a live send path are treated as failed attempts.
                if message.tries + 1 >= MAX_OUTBOX_RETRIES:
                    self._repository.mark_outbox_dead_letter(
                        message.outbox_id,
                        error_code=provider_result.error_code,
                        error_message=provider_result.error_message,
                    )
                else:
                    self._repository.mark_outbox_retry(
                        message.outbox_id,
                        error_code=provider_result.error_code,
                        error_message=provider_result.error_message,
                        now=_now_utc(),
                    )

        attempts = self._repository.list_attempts(run_id)
        outbox = self._repository.list_outbox_messages(run_id)
        outbox_by_attempt: dict[int, list[OutboxMessageRecord]] = {}
        for row in outbox:
            outbox_by_attempt.setdefault(row.attempt_id, []).append(row)

        results: list[ReminderResult] = []
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for attempt in attempts:
            if not attempt.eligible:
                skipped_count += 1
                result = ReminderResult(
                    invoice_id=attempt.invoice_id,
                    dispatch_id=attempt.dispatch_id,
                    status="skipped",
                    reason=attempt.reason,
                    next_eligible_at=attempt.next_eligible_at,
                    contact_target_masked=attempt.contact_target_masked,
                    channel_results=[],
                )
                results.append(result)
                self._repository.update_attempt_result(
                    attempt.attempt_id,
                    status="skipped",
                    reason=attempt.reason,
                    attempted_at=None,
                    provider_message_id=None,
                    error_code=None,
                    error_message=None,
                    channel_results=[],
                )
                continue

            if attempt.status in {"sent", "failed"}:
                parsed_channel_results = json.loads(attempt.channel_results_json)
                status = "sent" if attempt.status == "sent" else "failed"
                if status == "sent":
                    sent_count += 1
                else:
                    failed_count += 1
                results.append(
                    ReminderResult(
                        invoice_id=attempt.invoice_id,
                        dispatch_id=attempt.dispatch_id,
                        status=status,  # type: ignore[arg-type]
                        reason=attempt.reason,
                        attempted_at=attempt.attempted_at,
                        provider_message_id=attempt.provider_message_id,
                        error_code=attempt.error_code,
                        error_message=attempt.error_message,
                        next_eligible_at=(
                            attempt.attempted_at + timedelta(hours=48)
                            if attempt.attempted_at is not None
                            else None
                        ),
                        contact_target_masked=attempt.contact_target_masked,
                        channel_results=[
                            ReminderChannelResult(
                                channel=value.get("channel", "email"),  # type: ignore[arg-type]
                                status=value.get("status", "failed"),  # type: ignore[arg-type]
                                provider_message_id=value.get("provider_message_id")
                                if isinstance(value.get("provider_message_id"), str)
                                else None,
                                error_code=value.get("error_code") if isinstance(value.get("error_code"), str) else None,
                                error_message=value.get("error_message")
                                if isinstance(value.get("error_message"), str)
                                else None,
                            )
                            for value in parsed_channel_results
                            if isinstance(value, dict)
                        ],
                    )
                )
                continue

            channel_rows = sorted(outbox_by_attempt.get(attempt.attempt_id, []), key=lambda value: value.outbox_id)
            channel_results = [
                {
                    "channel": value.channel,
                    "status": "sent" if value.status == "sent" else "failed",
                    "provider_message_id": value.provider_message_id,
                    "error_code": value.error_code,
                    "error_message": value.error_message,
                }
                for value in channel_rows
            ]

            attempted_at = attempt.attempted_at or (run.run_at if channel_rows else None)
            all_sent = bool(channel_rows) and all(value.status == "sent" for value in channel_rows)
            any_pending = any(value.status in {"pending", "processing"} for value in channel_rows)
            if all_sent:
                sent_count += 1
                reason = "eligible"
                status = "sent"
            else:
                failed_count += 1
                reason = "provider_error" if channel_rows else "dispatch_missing"
                status = "failed"

            should_apply_state = False
            apply_success = False
            if attempted_at is not None and attempt.attempted_at is None:
                should_apply_state = True
                apply_success = all_sent
            elif attempted_at is not None and all_sent and attempt.status != "sent":
                should_apply_state = True
                apply_success = True

            if should_apply_state:
                self._store.apply_reminder_attempt_outcome(
                    attempt.invoice_id,
                    attempted_at=attempted_at,
                    all_channels_sent=apply_success,
                    dry_run=False,
                )

            first_message_id = next((row.get("provider_message_id") for row in channel_results if row.get("provider_message_id")), None)
            first_error_code = next((row.get("error_code") for row in channel_results if row.get("error_code")), None)
            first_error_message = next((row.get("error_message") for row in channel_results if row.get("error_message")), None)
            result = ReminderResult(
                invoice_id=attempt.invoice_id,
                dispatch_id=attempt.dispatch_id,
                status=status,  # type: ignore[arg-type]
                reason=reason,
                attempted_at=attempted_at,
                provider_message_id=first_message_id if isinstance(first_message_id, str) else None,
                error_code=first_error_code if isinstance(first_error_code, str) else None,
                error_message=first_error_message if isinstance(first_error_message, str) else None,
                next_eligible_at=(attempted_at + timedelta(hours=48)) if attempted_at is not None else None,
                contact_target_masked=attempt.contact_target_masked,
                channel_results=[
                    ReminderChannelResult(
                        channel=value["channel"],  # type: ignore[arg-type]
                        status=value["status"],  # type: ignore[arg-type]
                        provider_message_id=value["provider_message_id"] if isinstance(value["provider_message_id"], str) else None,
                        error_code=value["error_code"] if isinstance(value["error_code"], str) else None,
                        error_message=value["error_message"] if isinstance(value["error_message"], str) else None,
                    )
                    for value in channel_results
                ],
            )
            results.append(result)
            self._repository.update_attempt_result(
                attempt.attempt_id,
                status=status if (all_sent or not any_pending) else "planned",
                reason=reason,
                attempted_at=attempt.attempted_at or attempted_at,
                provider_message_id=first_message_id if isinstance(first_message_id, str) else None,
                error_code=first_error_code if isinstance(first_error_code, str) else None,
                error_message=first_error_message if isinstance(first_error_message, str) else None,
                channel_results=channel_results,
            )

        refreshed_outbox = self._repository.list_outbox_messages(run_id)
        has_pending = any(value.status in {"pending", "processing"} for value in refreshed_outbox)
        self._repository.finalize_run(
            run_id,
            status="processing" if has_pending else "completed",
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            escalated_count=run.escalated_count,
            finished_at=_now_utc(),
        )
        return ReminderRunResponse(
            run_id=run_id,
            run_at=run.run_at,
            dry_run=False,
            evaluated_count=run.evaluated_count,
            eligible_count=run.eligible_count,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            escalated_count=run.escalated_count,
            results=results,
        )

    def _build_dry_response(
        self,
        run_id: str,
        plan: PlannedReminderRun,
        idempotency_key: str | None,
    ) -> ReminderRunResponse:
        results: list[ReminderResult] = []
        for attempt in plan.attempts:
            if attempt.eligible:
                results.append(
                    ReminderResult(
                        invoice_id=attempt.invoice_id,
                        dispatch_id=attempt.dispatch_id,
                        status="dry_run",
                        reason="eligible_dry_run",
                        attempted_at=plan.run_at,
                        next_eligible_at=plan.run_at + timedelta(hours=48),
                        contact_target_masked=attempt.contact_target_masked,
                        idempotency_key=idempotency_key,
                        channel_results=[
                            ReminderChannelResult(
                                channel=channel.channel,  # type: ignore[arg-type]
                                status="dry_run",
                            )
                            for channel in attempt.channels
                        ],
                    )
                )
            else:
                results.append(
                    ReminderResult(
                        invoice_id=attempt.invoice_id,
                        dispatch_id=attempt.dispatch_id,
                        status="skipped",
                        reason=attempt.reason,
                        next_eligible_at=attempt.next_eligible_at,
                        contact_target_masked=attempt.contact_target_masked,
                        idempotency_key=idempotency_key,
                    )
                )
        return ReminderRunResponse(
            run_id=run_id,
            run_at=plan.run_at,
            dry_run=True,
            evaluated_count=plan.evaluated_count,
            eligible_count=plan.eligible_count,
            sent_count=0,
            failed_count=0,
            skipped_count=sum(1 for value in results if value.status == "skipped"),
            escalated_count=plan.escalated_count,
            results=results,
        )

    def _decode_provider_payload(self, payload: dict[str, object]):
        from .notifier import ProviderSendRequest

        due_date_raw = str(payload.get("due_date") or "")
        due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date()
        return ProviderSendRequest(
            invoice_id=str(payload.get("invoice_id") or ""),
            creator_id=str(payload.get("creator_id") or ""),
            creator_name=str(payload.get("creator_name") or ""),
            contact_channel=str(payload.get("contact_channel") or "email"),  # type: ignore[arg-type]
            contact_target=str(payload.get("contact_target") or ""),
            currency=str(payload.get("currency") or "USD"),
            amount_due=float(payload.get("amount_due") or 0.0),
            balance_due=float(payload.get("balance_due") or 0.0),
            due_date=due_date,
        )
