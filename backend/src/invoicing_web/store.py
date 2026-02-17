from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import count
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    Artifact,
    ArtifactListResponse,
    EscalationItem,
    InvoiceRecord,
    InvoiceUpsertRequest,
    PaymentEventRequest,
    PaymentEventResponse,
    PreviewRequest,
    ReminderResult,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderSummaryResponse,
    TaskDetail,
    TaskSummary,
)
from .openclaw import OpenClawSender, ProviderSendRequest, mask_contact_target

REMINDER_MAX_ATTEMPTS = 6
REMINDER_COOLDOWN = timedelta(hours=48)


class TaskNotFoundError(KeyError):
    """Raised when an operation references a task id that does not exist."""


class InvoiceNotFoundError(KeyError):
    """Raised when an operation references an invoice id that does not exist."""


@dataclass
class _TaskRecord:
    task_id: str
    status: str
    payload: PreviewRequest
    created_at: datetime
    updated_at: datetime


@dataclass
class _InvoiceRecord:
    invoice_id: str
    creator_id: str
    creator_name: str
    creator_timezone: str | None
    contact_channel: str
    contact_target: str
    currency: str
    amount_due: float
    amount_paid: float
    balance_due: float
    issued_at: date
    due_date: date
    status: str
    opt_out: bool
    reminder_count: int
    last_payment_at: datetime | None
    last_reminder_at: datetime | None
    updated_at: datetime


@dataclass
class _ReminderDecision:
    eligible: bool
    reason: str
    next_eligible_at: datetime | None = None


@dataclass
class _ReminderRunSnapshot:
    run_at: datetime
    dry_run: bool
    sent_count: int
    failed_count: int
    skipped_count: int


class InMemoryTaskStore:
    """Deterministic in-memory store with incremental task ids."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = count(1)
        self._tasks: dict[str, _TaskRecord] = {}
        self._artifacts: dict[str, list[Artifact]] = {}
        self._idempotency_index: dict[str, str] = {}

        self._invoices: dict[str, _InvoiceRecord] = {}
        self._payment_event_index: set[str] = set()
        self._reminder_logs: list[ReminderResult] = []
        self._last_reminder_run: _ReminderRunSnapshot | None = None

    def reset(self) -> None:
        with self._lock:
            self._counter = count(1)
            self._tasks.clear()
            self._artifacts.clear()
            self._idempotency_index.clear()

            self._invoices.clear()
            self._payment_event_index.clear()
            self._reminder_logs.clear()
            self._last_reminder_run = None

    def create_preview(self, payload: PreviewRequest) -> _TaskRecord:
        with self._lock:
            idem = payload.idempotency_key
            if idem:
                existing_task_id = self._idempotency_index.get(idem)
                if existing_task_id is not None:
                    existing_record = self._tasks.get(existing_task_id)
                    if existing_record is not None:
                        return existing_record

            now = datetime.now(timezone.utc)
            task_id = f"task-{next(self._counter):04d}"
            record = _TaskRecord(
                task_id=task_id,
                status="previewed",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = record
            self._artifacts[task_id] = []
            if idem:
                self._idempotency_index[idem] = task_id
            return record

    def confirm(self, task_id: str) -> _TaskRecord:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise TaskNotFoundError(task_id)
            if record.status == "previewed":
                record.status = "confirmed"
                record.updated_at = datetime.now(timezone.utc)
            return record

    def run_once(self) -> list[str]:
        processed: list[str] = []
        with self._lock:
            for task_id in sorted(self._tasks):
                record = self._tasks[task_id]
                if record.status != "confirmed":
                    continue
                record.status = "completed"
                record.updated_at = datetime.now(timezone.utc)
                self._artifacts[task_id] = [self._build_artifact(record)]
                processed.append(task_id)
        return processed

    def list_tasks(self) -> list[TaskSummary]:
        with self._lock:
            return [self._to_summary(self._tasks[task_id]) for task_id in sorted(self._tasks)]

    def get_task(self, task_id: str) -> TaskDetail:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise TaskNotFoundError(task_id)
            return self._to_detail(record)

    def get_artifacts(self, task_id: str) -> ArtifactListResponse:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            return ArtifactListResponse(
                task_id=task_id,
                artifacts=list(self._artifacts.get(task_id, [])),
            )

    def upsert_invoices(self, payload: InvoiceUpsertRequest) -> list[InvoiceRecord]:
        now = datetime.now(timezone.utc)
        upserted: list[InvoiceRecord] = []

        with self._lock:
            for item in payload.invoices:
                record = self._invoices.get(item.invoice_id)
                if record is None:
                    record = _InvoiceRecord(
                        invoice_id=item.invoice_id,
                        creator_id=item.creator_id,
                        creator_name=item.creator_name,
                        creator_timezone=item.creator_timezone,
                        contact_channel=item.contact_channel,
                        contact_target=item.contact_target,
                        currency=item.currency,
                        amount_due=self._round_amount(item.amount_due),
                        amount_paid=self._round_amount(item.amount_paid),
                        balance_due=self._round_amount(item.amount_due - item.amount_paid),
                        issued_at=item.issued_at,
                        due_date=item.due_date,
                        status="open",
                        opt_out=item.opt_out,
                        reminder_count=0,
                        last_payment_at=None,
                        last_reminder_at=None,
                        updated_at=now,
                    )
                    self._invoices[item.invoice_id] = record
                else:
                    record.creator_id = item.creator_id
                    record.creator_name = item.creator_name
                    record.creator_timezone = item.creator_timezone
                    record.contact_channel = item.contact_channel
                    record.contact_target = item.contact_target
                    record.currency = item.currency
                    record.amount_due = self._round_amount(item.amount_due)
                    record.amount_paid = self._round_amount(item.amount_paid)
                    record.balance_due = self._round_amount(record.amount_due - record.amount_paid)
                    record.issued_at = item.issued_at
                    record.due_date = item.due_date
                    record.opt_out = item.opt_out
                    record.updated_at = now

                self._refresh_invoice_status(record, now)
                upserted.append(self._to_invoice_record(record))

        return upserted

    def list_invoices(self) -> list[InvoiceRecord]:
        with self._lock:
            now = datetime.now(timezone.utc)
            records = sorted(self._invoices.values(), key=lambda value: (value.due_date, value.invoice_id))
            for record in records:
                self._refresh_invoice_status(record, now)
            return [self._to_invoice_record(record) for record in records]

    def apply_payment_event(self, payload: PaymentEventRequest) -> PaymentEventResponse:
        now = datetime.now(timezone.utc)

        with self._lock:
            record = self._invoices.get(payload.invoice_id)
            if record is None:
                raise InvoiceNotFoundError(payload.invoice_id)

            if payload.event_id in self._payment_event_index:
                self._refresh_invoice_status(record, now)
                return PaymentEventResponse(
                    event_id=payload.event_id,
                    invoice_id=record.invoice_id,
                    applied=False,
                    status=record.status,
                    balance_due=record.balance_due,
                )

            self._payment_event_index.add(payload.event_id)
            record.amount_paid = self._round_amount(min(record.amount_due, record.amount_paid + payload.amount))
            record.balance_due = self._round_amount(max(record.amount_due - record.amount_paid, 0))
            if record.last_payment_at is None or payload.paid_at > record.last_payment_at:
                record.last_payment_at = payload.paid_at
            record.updated_at = now
            self._refresh_invoice_status(record, now)

            return PaymentEventResponse(
                event_id=payload.event_id,
                invoice_id=record.invoice_id,
                applied=True,
                status=record.status,
                balance_due=record.balance_due,
            )

    def get_reminder_summary(self) -> ReminderSummaryResponse:
        with self._lock:
            now = datetime.now(timezone.utc)
            unpaid_count = 0
            overdue_count = 0
            eligible_now_count = 0

            for record in self._invoices.values():
                self._refresh_invoice_status(record, now)
                if record.balance_due > 0:
                    unpaid_count += 1
                if record.status in {"overdue", "escalated"} and record.balance_due > 0:
                    overdue_count += 1
                decision = self._evaluate_reminder(record, now)
                if decision.eligible:
                    eligible_now_count += 1

            escalated_count = len(self._current_escalations(now))
            snapshot = self._last_reminder_run

            return ReminderSummaryResponse(
                unpaid_count=unpaid_count,
                overdue_count=overdue_count,
                eligible_now_count=eligible_now_count,
                escalated_count=escalated_count,
                last_run_at=snapshot.run_at if snapshot else None,
                last_run_dry_run=snapshot.dry_run if snapshot else None,
                last_run_sent_count=snapshot.sent_count if snapshot else None,
                last_run_failed_count=snapshot.failed_count if snapshot else None,
                last_run_skipped_count=snapshot.skipped_count if snapshot else None,
            )

    def run_reminders(self, payload: ReminderRunRequest, sender: OpenClawSender) -> ReminderRunResponse:
        with self._lock:
            now = payload.now_override or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            else:
                now = now.astimezone(timezone.utc)

            records = sorted(self._invoices.values(), key=lambda value: (value.due_date, value.invoice_id))
            decisions: list[tuple[_InvoiceRecord, _ReminderDecision]] = []
            results: list[ReminderResult] = []

            for record in records:
                self._refresh_invoice_status(record, now)
                decision = self._evaluate_reminder(record, now)
                decisions.append((record, decision))

            eligible_count = sum(1 for _, decision in decisions if decision.eligible)
            sent_count = 0
            failed_count = 0
            processed_eligible = 0

            for record, decision in decisions:
                masked = mask_contact_target(record.contact_target, record.contact_channel)

                if not decision.eligible:
                    skipped_result = ReminderResult(
                        invoice_id=record.invoice_id,
                        status="skipped",
                        reason=decision.reason,
                        next_eligible_at=decision.next_eligible_at,
                        contact_target_masked=masked,
                    )
                    results.append(skipped_result)
                    self._reminder_logs.append(skipped_result)
                    continue

                if payload.limit is not None and processed_eligible >= payload.limit:
                    skipped_result = ReminderResult(
                        invoice_id=record.invoice_id,
                        status="skipped",
                        reason="limit_reached",
                        next_eligible_at=now + REMINDER_COOLDOWN,
                        contact_target_masked=masked,
                    )
                    results.append(skipped_result)
                    self._reminder_logs.append(skipped_result)
                    continue

                processed_eligible += 1
                provider_payload = ProviderSendRequest(
                    invoice_id=record.invoice_id,
                    creator_id=record.creator_id,
                    creator_name=record.creator_name,
                    contact_channel=record.contact_channel,
                    contact_target=record.contact_target,
                    currency=record.currency,
                    amount_due=record.amount_due,
                    balance_due=record.balance_due,
                    due_date=record.due_date,
                )
                provider_result = sender.send_friendly_reminder(provider_payload, dry_run=payload.dry_run)
                attempted_at = now

                reason = "eligible"
                reminder_status = "sent"
                if provider_result.status == "sent":
                    sent_count += 1
                    record.reminder_count += 1
                    record.last_reminder_at = attempted_at
                    record.updated_at = attempted_at
                    self._refresh_invoice_status(record, attempted_at)
                elif provider_result.status == "dry_run":
                    reminder_status = "dry_run"
                    reason = "eligible_dry_run"
                else:
                    failed_count += 1
                    reminder_status = "failed"
                    reason = "provider_error"

                result = ReminderResult(
                    invoice_id=record.invoice_id,
                    status=reminder_status,
                    reason=reason,
                    attempted_at=attempted_at,
                    provider_message_id=provider_result.provider_message_id,
                    error_code=provider_result.error_code,
                    error_message=provider_result.error_message,
                    next_eligible_at=(attempted_at + REMINDER_COOLDOWN)
                    if provider_result.status == "sent"
                    else None,
                    contact_target_masked=masked,
                )
                results.append(result)
                self._reminder_logs.append(result)

            skipped_count = sum(1 for result in results if result.status == "skipped")
            escalated_count = len(self._current_escalations(now))
            self._last_reminder_run = _ReminderRunSnapshot(
                run_at=now,
                dry_run=payload.dry_run,
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
            )

            return ReminderRunResponse(
                run_at=now,
                dry_run=payload.dry_run,
                evaluated_count=len(records),
                eligible_count=eligible_count,
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                escalated_count=escalated_count,
                results=results,
            )

    def list_escalations(self) -> list[EscalationItem]:
        with self._lock:
            now = datetime.now(timezone.utc)
            return self._current_escalations(now)

    def _build_artifact(self, record: _TaskRecord) -> Artifact:
        payload = record.payload
        lines = [
            f"task_id={record.task_id}",
            f"agent_slug={payload.agent_slug}",
            f"mode={payload.mode}",
            f"window_start={payload.window_start.isoformat()}",
            f"window_end={payload.window_end.isoformat()}",
            f"source_count={len(payload.source_refs)}",
            f"idempotency_key={payload.idempotency_key or ''}",
            f"principal_employee_id={payload.principal_employee_id or ''}",
        ]
        for index, source_ref in enumerate(payload.source_refs, start=1):
            lines.append(f"source_ref_{index}={source_ref}")
        for key in sorted(payload.metadata):
            lines.append(f"metadata.{key}={payload.metadata[key]}")
        return Artifact(
            filename=f"invoicing-task-{record.task_id}.txt",
            content_type="text/plain",
            content="\n".join(lines),
        )

    def _to_summary(self, record: _TaskRecord) -> TaskSummary:
        payload = record.payload
        return TaskSummary(
            task_id=record.task_id,
            status=record.status,
            agent_slug=payload.agent_slug,
            mode=payload.mode,
            window_start=payload.window_start,
            window_end=payload.window_end,
            source_count=len(payload.source_refs),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_detail(self, record: _TaskRecord) -> TaskDetail:
        payload = record.payload
        return TaskDetail(
            task_id=record.task_id,
            status=record.status,
            agent_slug=payload.agent_slug,
            mode=payload.mode,
            window_start=payload.window_start,
            window_end=payload.window_end,
            source_refs=list(payload.source_refs),
            idempotency_key=payload.idempotency_key,
            principal_employee_id=payload.principal_employee_id,
            metadata=dict(payload.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_invoice_record(self, record: _InvoiceRecord) -> InvoiceRecord:
        return InvoiceRecord(
            invoice_id=record.invoice_id,
            creator_id=record.creator_id,
            creator_name=record.creator_name,
            creator_timezone=record.creator_timezone,
            contact_channel=record.contact_channel,
            contact_target_masked=mask_contact_target(record.contact_target, record.contact_channel),
            currency=record.currency,
            amount_due=record.amount_due,
            amount_paid=record.amount_paid,
            balance_due=record.balance_due,
            issued_at=record.issued_at,
            due_date=record.due_date,
            status=record.status,
            opt_out=record.opt_out,
            reminder_count=record.reminder_count,
            last_payment_at=record.last_payment_at,
            last_reminder_at=record.last_reminder_at,
            updated_at=record.updated_at,
        )

    def _evaluate_reminder(self, record: _InvoiceRecord, now: datetime) -> _ReminderDecision:
        if record.opt_out:
            return _ReminderDecision(eligible=False, reason="opt_out")

        if record.balance_due <= 0 or record.status == "paid":
            return _ReminderDecision(eligible=False, reason="paid")

        if record.reminder_count >= REMINDER_MAX_ATTEMPTS:
            record.status = "escalated"
            return _ReminderDecision(eligible=False, reason="max_reminders_reached")

        due_at = self._due_at_utc(record)
        if now < due_at:
            return _ReminderDecision(eligible=False, reason="not_due_yet", next_eligible_at=due_at)

        if record.last_reminder_at is not None:
            next_allowed = record.last_reminder_at + REMINDER_COOLDOWN
            if now < next_allowed:
                return _ReminderDecision(eligible=False, reason="cooldown_active", next_eligible_at=next_allowed)

        return _ReminderDecision(eligible=True, reason="eligible", next_eligible_at=now)

    def _current_escalations(self, now: datetime) -> list[EscalationItem]:
        escalations: list[EscalationItem] = []
        for record in sorted(self._invoices.values(), key=lambda value: (value.due_date, value.invoice_id)):
            self._refresh_invoice_status(record, now)
            if record.balance_due <= 0:
                continue
            if record.reminder_count < REMINDER_MAX_ATTEMPTS:
                continue

            record.status = "escalated"
            escalations.append(
                EscalationItem(
                    invoice_id=record.invoice_id,
                    creator_id=record.creator_id,
                    creator_name=record.creator_name,
                    balance_due=record.balance_due,
                    due_date=record.due_date,
                    reminder_count=record.reminder_count,
                    last_reminder_at=record.last_reminder_at,
                    reason="max_reminders_reached",
                )
            )

        return escalations

    def _refresh_invoice_status(self, record: _InvoiceRecord, now: datetime) -> None:
        if record.balance_due <= 0:
            record.status = "paid"
            return

        if record.reminder_count >= REMINDER_MAX_ATTEMPTS:
            record.status = "escalated"
            return

        if self._is_due_started(record, now):
            record.status = "overdue"
            return

        if record.amount_paid > 0:
            record.status = "partial"
            return

        record.status = "open"

    def _is_due_started(self, record: _InvoiceRecord, now: datetime) -> bool:
        return now >= self._due_at_utc(record)

    def _due_at_utc(self, record: _InvoiceRecord) -> datetime:
        zone = self._resolve_timezone(record.creator_timezone)
        due_local = datetime.combine(record.due_date, time.min, tzinfo=zone)
        return due_local.astimezone(timezone.utc)

    def _resolve_timezone(self, zone_name: str | None) -> timezone | ZoneInfo:
        if not zone_name:
            return timezone.utc
        try:
            return ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            return timezone.utc

    def _round_amount(self, value: float) -> float:
        return round(float(value), 2)
