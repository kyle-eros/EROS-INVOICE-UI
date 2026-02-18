from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from itertools import count
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    AchExchangeRequest,
    AchExchangeResponse,
    AchLinkTokenRequest,
    AchLinkTokenResponse,
    Artifact,
    ArtifactListResponse,
    CreatorDispatchAcknowledgeResponse,
    CreatorInvoiceItem,
    CreatorInvoicesResponse,
    EscalationItem,
    InvoiceDetailPayload,
    InvoiceDispatchRequest,
    InvoiceDispatchResponse,
    InvoicePdfContext,
    InvoiceRecord,
    InvoiceUpsertRequest,
    PaymentCheckoutSessionRequest,
    PaymentCheckoutSessionResponse,
    PaymentEventRequest,
    PaymentEventResponse,
    PaymentInvoiceStatusResponse,
    PaymentIntentStatus,
    PaymentWebhookEventRequest,
    PaymentWebhookEventResponse,
    PayoutItem,
    PayoutListResponse,
    PreviewRequest,
    ReconciliationCaseItem,
    ReconciliationCaseResolveRequest,
    ReconciliationCaseResolveResponse,
    ReminderChannelResult,
    ReminderResult,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderStatus,
    ReminderSummaryResponse,
    TaskDetail,
    TaskSummary,
)
from .notifier import NotifierSender, ProviderSendRequest, mask_contact_target

REMINDER_MAX_ATTEMPTS = 6
REMINDER_COOLDOWN = timedelta(hours=48)


class TaskNotFoundError(KeyError):
    """Raised when an operation references a task id that does not exist."""


class InvoiceNotFoundError(KeyError):
    """Raised when an operation references an invoice id that does not exist."""


class InvoiceDetailNotFoundError(KeyError):
    """Raised when an invoice exists but has no detail payload for PDF rendering."""


class DispatchNotFoundError(KeyError):
    """Raised when a dispatch id does not exist."""


class CreatorNotFoundError(KeyError):
    """Raised when a creator id is not present in invoice records."""


class ReconciliationCaseNotFoundError(KeyError):
    """Raised when a reconciliation case id does not exist."""


class PayoutNotFoundError(KeyError):
    """Raised when a payout id does not exist."""


RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW = timedelta(minutes=15)


@dataclass
class _PasskeyRecord:
    creator_id: str
    creator_name: str
    passkey_hash: str
    display_prefix: str
    created_at: datetime


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
    dispatch_id: str | None
    dispatched_at: datetime | None
    notification_state: str
    last_payment_at: datetime | None
    last_reminder_at: datetime | None
    updated_at: datetime
    detail: InvoiceDetailPayload | None


@dataclass
class _DispatchRecord:
    dispatch_id: str
    invoice_id: str
    creator_id: str
    channels: list[str]
    recipient_email: str | None
    recipient_phone: str | None
    creator_portal_url: str | None
    dispatched_at: datetime
    idempotency_key: str | None


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


@dataclass
class _PaymentCheckoutSessionRecord:
    checkout_session_id: str
    invoice_id: str
    provider: str
    status: PaymentIntentStatus
    amount_due: float
    currency: str
    client_token: str
    available_methods: list[str]
    expires_at: datetime
    idempotency_key: str | None
    created_at: datetime


@dataclass
class _ReconciliationCaseRecord:
    case_id: str
    provider: str
    event_id: str
    invoice_id: str | None
    reason: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


@dataclass
class _PayoutRecord:
    payout_id: str
    invoice_id: str
    amount: float
    currency: str
    destination_label: str
    provider: str
    status: str
    created_at: datetime
    settled_at: datetime | None = None


class InMemoryTaskStore:
    """Deterministic in-memory store with incremental task ids."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = count(1)
        self._tasks: dict[str, _TaskRecord] = {}
        self._artifacts: dict[str, list[Artifact]] = {}
        self._idempotency_index: dict[str, str] = {}

        self._invoices: dict[str, _InvoiceRecord] = {}
        self._dispatch_counter = count(1)
        self._dispatches: dict[str, _DispatchRecord] = {}
        self._dispatch_by_invoice: dict[str, str] = {}
        self._dispatch_idempotency: dict[str, str] = {}

        self._payment_event_index: set[str] = set()
        self._checkout_counter = count(1)
        self._checkout_sessions: dict[str, _PaymentCheckoutSessionRecord] = {}
        self._checkout_idempotency: dict[str, str] = {}
        self._latest_checkout_by_invoice: dict[str, str] = {}
        self._webhook_event_index: set[str] = set()
        self._reconciliation_counter = count(1)
        self._reconciliation_cases: dict[str, _ReconciliationCaseRecord] = {}
        self._payout_counter = count(1)
        self._payouts: dict[str, _PayoutRecord] = {}
        self._reminder_logs: list[ReminderResult] = []
        self._last_reminder_run: _ReminderRunSnapshot | None = None
        self._reminder_run_idempotency: dict[str, ReminderRunResponse] = {}

        self._passkeys: dict[str, _PasskeyRecord] = {}
        self._passkey_hash_index: dict[str, str] = {}
        self._revoked_creators: set[str] = set()
        self._login_attempts: dict[str, list[datetime]] = {}
        self._revoked_broker_tokens: set[str] = set()

    def reset(self) -> None:
        with self._lock:
            self._counter = count(1)
            self._tasks.clear()
            self._artifacts.clear()
            self._idempotency_index.clear()

            self._invoices.clear()
            self._dispatch_counter = count(1)
            self._dispatches.clear()
            self._dispatch_by_invoice.clear()
            self._dispatch_idempotency.clear()

            self._payment_event_index.clear()
            self._checkout_counter = count(1)
            self._checkout_sessions.clear()
            self._checkout_idempotency.clear()
            self._latest_checkout_by_invoice.clear()
            self._webhook_event_index.clear()
            self._reconciliation_counter = count(1)
            self._reconciliation_cases.clear()
            self._payout_counter = count(1)
            self._payouts.clear()
            self._reminder_logs.clear()
            self._last_reminder_run = None
            self._reminder_run_idempotency.clear()

            self._passkeys.clear()
            self._passkey_hash_index.clear()
            self._revoked_creators.clear()
            self._login_attempts.clear()
            self._revoked_broker_tokens.clear()

    def generate_passkey(self, creator_id: str, creator_name: str) -> tuple[_PasskeyRecord, str]:
        with self._lock:
            raw_passkey = secrets.token_urlsafe(32)
            passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
            display_prefix = raw_passkey[:6]
            now = datetime.now(timezone.utc)

            old_record = self._passkeys.get(creator_id)
            if old_record is not None:
                self._passkey_hash_index.pop(old_record.passkey_hash, None)

            record = _PasskeyRecord(
                creator_id=creator_id,
                creator_name=creator_name,
                passkey_hash=passkey_hash,
                display_prefix=display_prefix,
                created_at=now,
            )
            self._passkeys[creator_id] = record
            self._passkey_hash_index[passkey_hash] = creator_id
            self._revoked_creators.discard(creator_id)
            return record, raw_passkey

    def lookup_by_passkey(self, raw_passkey: str) -> _PasskeyRecord | None:
        with self._lock:
            passkey_hash = hashlib.sha256(raw_passkey.encode("utf-8")).hexdigest()
            creator_id = self._passkey_hash_index.get(passkey_hash)
            if creator_id is None:
                return None
            return self._passkeys.get(creator_id)

    def revoke_passkey(self, creator_id: str) -> bool:
        with self._lock:
            record = self._passkeys.pop(creator_id, None)
            if record is None:
                return False
            self._passkey_hash_index.pop(record.passkey_hash, None)
            self._revoked_creators.add(creator_id)
            return True

    def list_passkeys(self) -> list[_PasskeyRecord]:
        with self._lock:
            return list(self._passkeys.values())

    def is_creator_revoked(self, creator_id: str) -> bool:
        with self._lock:
            return creator_id in self._revoked_creators

    def check_rate_limit(self, client_ip: str) -> bool:
        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - RATE_LIMIT_WINDOW
            attempts = self._login_attempts.get(client_ip, [])
            recent = [ts for ts in attempts if ts > cutoff]
            self._login_attempts[client_ip] = recent
            return len(recent) < RATE_LIMIT_MAX_ATTEMPTS

    def record_failed_attempt(self, client_ip: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            if client_ip not in self._login_attempts:
                self._login_attempts[client_ip] = []
            self._login_attempts[client_ip].append(now)

    def revoke_broker_token(self, token_id: str) -> None:
        with self._lock:
            self._revoked_broker_tokens.add(token_id)

    def is_broker_token_revoked(self, token_id: str) -> bool:
        with self._lock:
            return token_id in self._revoked_broker_tokens

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

    def creator_exists(self, creator_id: str) -> bool:
        with self._lock:
            return any(record.creator_id == creator_id for record in self._invoices.values())

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
                        dispatch_id=None,
                        dispatched_at=None,
                        notification_state="unseen",
                        last_payment_at=None,
                        last_reminder_at=None,
                        updated_at=now,
                        detail=item.detail.model_copy(deep=True) if item.detail is not None else None,
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
                    record.detail = item.detail.model_copy(deep=True) if item.detail is not None else None

                self._refresh_invoice_status(record, now)
                self._refresh_invoice_notification(record)
                upserted.append(self._to_invoice_record(record))

        return upserted

    def list_invoices(self) -> list[InvoiceRecord]:
        with self._lock:
            now = datetime.now(timezone.utc)
            records = sorted(self._invoices.values(), key=lambda value: (value.due_date, value.invoice_id))
            for record in records:
                self._refresh_invoice_status(record, now)
                self._refresh_invoice_notification(record)
            return [self._to_invoice_record(record) for record in records]

    def dispatch_invoice(self, payload: InvoiceDispatchRequest) -> InvoiceDispatchResponse:
        with self._lock:
            now = payload.dispatched_at or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            else:
                now = now.astimezone(timezone.utc)

            record = self._invoices.get(payload.invoice_id)
            if record is None:
                raise InvoiceNotFoundError(payload.invoice_id)

            idem = payload.idempotency_key
            if idem and idem in self._dispatch_idempotency:
                existing_dispatch_id = self._dispatch_idempotency[idem]
                existing_dispatch = self._dispatches[existing_dispatch_id]
                return self._to_dispatch_response(existing_dispatch, record.notification_state)

            existing_dispatch_id = self._dispatch_by_invoice.get(payload.invoice_id)
            if existing_dispatch_id:
                existing_dispatch = self._dispatches[existing_dispatch_id]
                if idem:
                    self._dispatch_idempotency[idem] = existing_dispatch_id
                return self._to_dispatch_response(existing_dispatch, record.notification_state)

            dispatch_id = f"dispatch-{next(self._dispatch_counter):04d}"
            dispatch = _DispatchRecord(
                dispatch_id=dispatch_id,
                invoice_id=payload.invoice_id,
                creator_id=record.creator_id,
                channels=list(payload.channels),
                recipient_email=payload.recipient_email,
                recipient_phone=payload.recipient_phone,
                creator_portal_url=payload.creator_portal_url,
                dispatched_at=now,
                idempotency_key=idem,
            )
            self._dispatches[dispatch_id] = dispatch
            self._dispatch_by_invoice[payload.invoice_id] = dispatch_id
            if idem:
                self._dispatch_idempotency[idem] = dispatch_id

            record.dispatch_id = dispatch_id
            record.dispatched_at = now
            record.updated_at = now
            self._refresh_invoice_status(record, now)
            self._refresh_invoice_notification(record)

            return self._to_dispatch_response(dispatch, record.notification_state)

    def acknowledge_dispatch(self, dispatch_id: str) -> CreatorDispatchAcknowledgeResponse:
        with self._lock:
            dispatch = self._dispatches.get(dispatch_id)
            if dispatch is None:
                raise DispatchNotFoundError(dispatch_id)

            record = self._invoices.get(dispatch.invoice_id)
            if record is None:
                raise InvoiceNotFoundError(dispatch.invoice_id)

            acknowledged_at = datetime.now(timezone.utc)
            self._refresh_invoice_status(record, acknowledged_at)
            if record.balance_due <= 0:
                record.notification_state = "fulfilled"
            else:
                record.notification_state = "seen_unfulfilled"
            record.updated_at = acknowledged_at

            return CreatorDispatchAcknowledgeResponse(
                dispatch_id=dispatch.dispatch_id,
                invoice_id=record.invoice_id,
                creator_id=record.creator_id,
                notification_state=record.notification_state,
                acknowledged_at=acknowledged_at,
            )

    def get_creator_invoices(self, creator_id: str) -> CreatorInvoicesResponse:
        with self._lock:
            records = [
                record
                for record in self._invoices.values()
                if record.creator_id == creator_id and record.dispatch_id is not None
            ]
            if not records:
                raise CreatorNotFoundError(creator_id)

            now = datetime.now(timezone.utc)
            records.sort(key=lambda value: (value.due_date, value.invoice_id))
            items: list[CreatorInvoiceItem] = []
            for record in records:
                self._refresh_invoice_status(record, now)
                self._refresh_invoice_notification(record)
                if record.dispatch_id is None or record.dispatched_at is None:
                    continue
                items.append(
                    CreatorInvoiceItem(
                        invoice_id=record.invoice_id,
                        amount_due=record.amount_due,
                        amount_paid=record.amount_paid,
                        balance_due=record.balance_due,
                        issued_at=record.issued_at,
                        due_date=record.due_date,
                        status=record.status,
                        dispatch_id=record.dispatch_id,
                        dispatched_at=record.dispatched_at,
                        notification_state=record.notification_state,
                        reminder_count=record.reminder_count,
                        has_pdf=record.detail is not None,
                        last_reminder_at=record.last_reminder_at,
                    )
                )

            creator_name = records[0].creator_name
            return CreatorInvoicesResponse(creator_id=creator_id, creator_name=creator_name, invoices=items)

    def get_creator_invoice_pdf(self, creator_id: str, invoice_id: str) -> InvoicePdfContext:
        with self._lock:
            record = self._invoices.get(invoice_id)
            if (
                record is None
                or record.creator_id != creator_id
                or record.dispatch_id is None
                or record.dispatched_at is None
            ):
                raise InvoiceNotFoundError(invoice_id)
            if record.detail is None:
                raise InvoiceDetailNotFoundError(invoice_id)

            now = datetime.now(timezone.utc)
            self._refresh_invoice_status(record, now)
            self._refresh_invoice_notification(record)
            return InvoicePdfContext(
                invoice_id=record.invoice_id,
                creator_id=record.creator_id,
                creator_name=record.creator_name,
                issued_at=record.issued_at,
                due_date=record.due_date,
                currency=record.currency,
                amount_due=record.amount_due,
                detail=record.detail.model_copy(deep=True),
            )

    def create_checkout_session(
        self,
        payload: PaymentCheckoutSessionRequest,
        *,
        provider_name: str,
    ) -> PaymentCheckoutSessionResponse:
        with self._lock:
            record = self._invoices.get(payload.invoice_id)
            if record is None:
                raise InvoiceNotFoundError(payload.invoice_id)
            if record.balance_due <= 0:
                raise ValueError("invoice is already fully paid")

            idem = payload.idempotency_key
            if idem and idem in self._checkout_idempotency:
                existing_id = self._checkout_idempotency[idem]
                existing = self._checkout_sessions.get(existing_id)
                if existing is not None:
                    return self._to_checkout_response(existing)

            now = datetime.now(timezone.utc)
            checkout_id = f"chk_{next(self._checkout_counter):06d}"
            session = _PaymentCheckoutSessionRecord(
                checkout_session_id=checkout_id,
                invoice_id=record.invoice_id,
                provider=provider_name,
                status="requires_payment_method",
                amount_due=record.balance_due,
                currency=record.currency,
                client_token=secrets.token_urlsafe(24),
                available_methods=list(payload.payment_methods),
                expires_at=now + timedelta(minutes=30),
                idempotency_key=idem,
                created_at=now,
            )
            self._checkout_sessions[checkout_id] = session
            self._latest_checkout_by_invoice[record.invoice_id] = checkout_id
            if idem:
                self._checkout_idempotency[idem] = checkout_id
            return self._to_checkout_response(session)

    def create_ach_link_token(
        self,
        payload: AchLinkTokenRequest,
        *,
        provider_name: str,
    ) -> AchLinkTokenResponse:
        now = datetime.now(timezone.utc)
        token = f"link_{payload.creator_id}_{secrets.token_urlsafe(18)}"
        return AchLinkTokenResponse(
            provider=provider_name,
            link_token=token,
            expires_at=now + timedelta(minutes=30),
        )

    def exchange_ach_token(
        self,
        payload: AchExchangeRequest,
        *,
        provider_name: str,
    ) -> AchExchangeResponse:
        token_tail = payload.account_id[-4:] if len(payload.account_id) >= 4 else payload.account_id
        return AchExchangeResponse(
            provider=provider_name,
            payment_method_id=f"pm_ach_{secrets.token_urlsafe(8)}",
            creator_id=payload.creator_id,
            account_mask=f"****{token_tail}",
            bank_name="Verified ACH Account",
            status="requires_payment_method",
        )

    def get_payment_invoice_status(self, invoice_id: str) -> PaymentInvoiceStatusResponse:
        with self._lock:
            record = self._invoices.get(invoice_id)
            if record is None:
                raise InvoiceNotFoundError(invoice_id)
            now = datetime.now(timezone.utc)
            self._refresh_invoice_status(record, now)
            self._refresh_invoice_notification(record)

            latest_checkout_id = self._latest_checkout_by_invoice.get(invoice_id)
            latest_checkout = self._checkout_sessions.get(latest_checkout_id or "")
            return PaymentInvoiceStatusResponse(
                invoice_id=record.invoice_id,
                status=record.status,
                amount_due=record.amount_due,
                amount_paid=record.amount_paid,
                balance_due=record.balance_due,
                currency=record.currency,
                latest_checkout_session_id=latest_checkout.checkout_session_id if latest_checkout else None,
                latest_checkout_status=latest_checkout.status if latest_checkout else None,
                last_payment_at=record.last_payment_at,
            )

    def apply_payment_webhook(
        self,
        provider: str,
        payload: PaymentWebhookEventRequest,
        *,
        settlement_destination_label: str,
    ) -> PaymentWebhookEventResponse:
        with self._lock:
            event_key = f"{provider}:{payload.event_id}"
            if event_key in self._webhook_event_index:
                return PaymentWebhookEventResponse(
                    provider=provider,
                    event_id=payload.event_id,
                    applied=False,
                    invoice_id=payload.invoice_id,
                )

            self._webhook_event_index.add(event_key)
            now = payload.occurred_at or datetime.now(timezone.utc)

            normalized_status = payload.status.strip().lower()
            if normalized_status not in {"succeeded", "settled"}:
                case = self._create_reconciliation_case(
                    provider=provider,
                    event_id=payload.event_id,
                    invoice_id=payload.invoice_id,
                    reason=f"unsupported_status:{normalized_status}",
                    created_at=now,
                )
                return PaymentWebhookEventResponse(
                    provider=provider,
                    event_id=payload.event_id,
                    applied=False,
                    invoice_id=payload.invoice_id,
                    reconciliation_case_id=case.case_id,
                )

            if payload.invoice_id is None or payload.amount is None:
                case = self._create_reconciliation_case(
                    provider=provider,
                    event_id=payload.event_id,
                    invoice_id=payload.invoice_id,
                    reason="missing_invoice_or_amount",
                    created_at=now,
                )
                return PaymentWebhookEventResponse(
                    provider=provider,
                    event_id=payload.event_id,
                    applied=False,
                    invoice_id=payload.invoice_id,
                    reconciliation_case_id=case.case_id,
                )

            record = self._invoices.get(payload.invoice_id)
            if record is None:
                case = self._create_reconciliation_case(
                    provider=provider,
                    event_id=payload.event_id,
                    invoice_id=payload.invoice_id,
                    reason="invoice_not_found",
                    created_at=now,
                )
                return PaymentWebhookEventResponse(
                    provider=provider,
                    event_id=payload.event_id,
                    applied=False,
                    invoice_id=payload.invoice_id,
                    reconciliation_case_id=case.case_id,
                )

            event_response = self._apply_payment_event_locked(
                event_id=payload.event_id,
                record=record,
                amount=payload.amount,
                paid_at=now,
                source=f"webhook:{provider}",
            )

            latest_checkout_id = self._latest_checkout_by_invoice.get(record.invoice_id)
            latest_checkout = self._checkout_sessions.get(latest_checkout_id or "")
            if latest_checkout is not None:
                latest_checkout.status = "succeeded"

            if event_response.applied:
                self._record_payout_if_settled(
                    record=record,
                    amount=payload.amount,
                    provider=provider,
                    destination_label=settlement_destination_label,
                    settled_at=now,
                )

            return PaymentWebhookEventResponse(
                provider=provider,
                event_id=payload.event_id,
                applied=event_response.applied,
                invoice_id=record.invoice_id,
                payment_status=event_response.status,
                balance_due=event_response.balance_due,
            )

    def list_reconciliation_cases(self) -> list[ReconciliationCaseItem]:
        with self._lock:
            records = sorted(
                self._reconciliation_cases.values(),
                key=lambda value: value.created_at,
                reverse=True,
            )
            return [self._to_reconciliation_case_item(value) for value in records]

    def resolve_reconciliation_case(
        self,
        case_id: str,
        payload: ReconciliationCaseResolveRequest,
    ) -> ReconciliationCaseResolveResponse:
        with self._lock:
            case = self._reconciliation_cases.get(case_id)
            if case is None:
                raise ReconciliationCaseNotFoundError(case_id)
            resolved_at = datetime.now(timezone.utc)
            case.status = "resolved"
            case.resolved_at = resolved_at
            case.resolution_note = payload.resolution_note
            return ReconciliationCaseResolveResponse(
                case_id=case.case_id,
                status="resolved",
                resolved_at=resolved_at,
                resolution_note=payload.resolution_note,
            )

    def list_payouts(self) -> PayoutListResponse:
        with self._lock:
            records = sorted(
                self._payouts.values(),
                key=lambda value: value.created_at,
                reverse=True,
            )
            return PayoutListResponse(items=[self._to_payout_item(value) for value in records])

    def get_payout(self, payout_id: str) -> PayoutItem:
        with self._lock:
            payout = self._payouts.get(payout_id)
            if payout is None:
                raise PayoutNotFoundError(payout_id)
            return self._to_payout_item(payout)

    def apply_payment_event(self, payload: PaymentEventRequest) -> PaymentEventResponse:
        with self._lock:
            record = self._invoices.get(payload.invoice_id)
            if record is None:
                raise InvoiceNotFoundError(payload.invoice_id)
            return self._apply_payment_event_locked(
                event_id=payload.event_id,
                record=record,
                amount=payload.amount,
                paid_at=payload.paid_at,
                source=payload.source,
            )

    def get_reminder_summary(self) -> ReminderSummaryResponse:
        with self._lock:
            now = datetime.now(timezone.utc)
            unpaid_count = 0
            overdue_count = 0
            eligible_now_count = 0

            for record in self._invoices.values():
                self._refresh_invoice_status(record, now)
                self._refresh_invoice_notification(record)
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

    def run_reminders(self, payload: ReminderRunRequest, sender: NotifierSender) -> ReminderRunResponse:
        with self._lock:
            if payload.idempotency_key and payload.idempotency_key in self._reminder_run_idempotency:
                return self._reminder_run_idempotency[payload.idempotency_key]

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
                self._refresh_invoice_notification(record)
                decision = self._evaluate_reminder(record, now)
                decisions.append((record, decision))

            eligible_count = sum(1 for _, decision in decisions if decision.eligible)
            sent_count = 0
            failed_count = 0
            processed_eligible = 0

            for record, decision in decisions:
                dispatch = self._dispatches.get(record.dispatch_id or "") if record.dispatch_id else None
                masked_targets = self._masked_dispatch_targets(dispatch)

                if not decision.eligible:
                    skipped_result = ReminderResult(
                        invoice_id=record.invoice_id,
                        dispatch_id=record.dispatch_id,
                        status="skipped",
                        reason=decision.reason,
                        next_eligible_at=decision.next_eligible_at,
                        contact_target_masked=masked_targets,
                        idempotency_key=payload.idempotency_key,
                    )
                    results.append(skipped_result)
                    self._reminder_logs.append(skipped_result)
                    continue

                if payload.limit is not None and processed_eligible >= payload.limit:
                    skipped_result = ReminderResult(
                        invoice_id=record.invoice_id,
                        dispatch_id=record.dispatch_id,
                        status="skipped",
                        reason="limit_reached",
                        next_eligible_at=now + REMINDER_COOLDOWN,
                        contact_target_masked=masked_targets,
                        idempotency_key=payload.idempotency_key,
                    )
                    results.append(skipped_result)
                    self._reminder_logs.append(skipped_result)
                    continue

                processed_eligible += 1
                channel_results: list[ReminderChannelResult] = []

                if dispatch is None:
                    channel_results.append(
                        ReminderChannelResult(
                            channel="email",
                            status="failed",
                            error_code="dispatch_missing",
                            error_message="Dispatch record missing for eligible invoice",
                        )
                    )
                else:
                    for channel in dispatch.channels:
                        recipient = dispatch.recipient_email if channel == "email" else dispatch.recipient_phone
                        if not recipient:
                            channel_results.append(
                                ReminderChannelResult(
                                    channel=channel,
                                    status="failed",
                                    error_code="recipient_missing",
                                    error_message=f"Recipient missing for channel {channel}",
                                )
                            )
                            continue

                        provider_payload = ProviderSendRequest(
                            invoice_id=record.invoice_id,
                            creator_id=record.creator_id,
                            creator_name=record.creator_name,
                            contact_channel=channel,
                            contact_target=recipient,
                            currency=record.currency,
                            amount_due=record.amount_due,
                            balance_due=record.balance_due,
                            due_date=record.due_date,
                        )
                        provider_result = sender.send_friendly_reminder(provider_payload, dry_run=payload.dry_run)
                        channel_results.append(
                            ReminderChannelResult(
                                channel=channel,
                                status=provider_result.status,
                                provider_message_id=provider_result.provider_message_id,
                                error_code=provider_result.error_code,
                                error_message=provider_result.error_message,
                            )
                        )

                statuses = [result.status for result in channel_results]
                attempted_at = now
                summary_status: ReminderStatus
                reason = "eligible"

                if statuses and all(status == "dry_run" for status in statuses):
                    summary_status = "dry_run"
                    reason = "eligible_dry_run"
                elif statuses and all(status == "sent" for status in statuses):
                    summary_status = "sent"
                    sent_count += 1
                    record.reminder_count += 1
                    record.last_reminder_at = attempted_at
                    record.updated_at = attempted_at
                    self._refresh_invoice_status(record, attempted_at)
                    self._refresh_invoice_notification(record)
                else:
                    summary_status = "failed"
                    failed_count += 1
                    reason = "provider_error"

                first_message_id = next((value.provider_message_id for value in channel_results if value.provider_message_id), None)
                first_error_code = next((value.error_code for value in channel_results if value.error_code), None)
                first_error_message = next((value.error_message for value in channel_results if value.error_message), None)

                result = ReminderResult(
                    invoice_id=record.invoice_id,
                    dispatch_id=record.dispatch_id,
                    status=summary_status,
                    reason=reason,
                    attempted_at=attempted_at,
                    provider_message_id=first_message_id,
                    error_code=first_error_code,
                    error_message=first_error_message,
                    next_eligible_at=(attempted_at + REMINDER_COOLDOWN) if summary_status == "sent" else None,
                    contact_target_masked=masked_targets,
                    idempotency_key=payload.idempotency_key,
                    channel_results=channel_results,
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

            response = ReminderRunResponse(
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
            if payload.idempotency_key:
                self._reminder_run_idempotency[payload.idempotency_key] = response
            return response

    def list_escalations(self) -> list[EscalationItem]:
        with self._lock:
            now = datetime.now(timezone.utc)
            return self._current_escalations(now)

    def _apply_payment_event_locked(
        self,
        *,
        event_id: str,
        record: _InvoiceRecord,
        amount: float,
        paid_at: datetime,
        source: str,
    ) -> PaymentEventResponse:
        now = datetime.now(timezone.utc)
        if event_id in self._payment_event_index:
            self._refresh_invoice_status(record, now)
            self._refresh_invoice_notification(record)
            return PaymentEventResponse(
                event_id=event_id,
                invoice_id=record.invoice_id,
                applied=False,
                status=record.status,
                balance_due=record.balance_due,
            )

        self._payment_event_index.add(event_id)
        record.amount_paid = self._round_amount(min(record.amount_due, record.amount_paid + amount))
        record.balance_due = self._round_amount(max(record.amount_due - record.amount_paid, 0))
        if record.last_payment_at is None or paid_at > record.last_payment_at:
            record.last_payment_at = paid_at
        record.updated_at = now
        self._refresh_invoice_status(record, now)
        self._refresh_invoice_notification(record)

        latest_checkout_id = self._latest_checkout_by_invoice.get(record.invoice_id)
        latest_checkout = self._checkout_sessions.get(latest_checkout_id or "")
        if latest_checkout is not None:
            latest_checkout.status = "succeeded" if record.balance_due <= 0 else "processing"

        _ = source  # retained for future provider-specific routing.
        return PaymentEventResponse(
            event_id=event_id,
            invoice_id=record.invoice_id,
            applied=True,
            status=record.status,
            balance_due=record.balance_due,
        )

    def _create_reconciliation_case(
        self,
        *,
        provider: str,
        event_id: str,
        invoice_id: str | None,
        reason: str,
        created_at: datetime,
    ) -> _ReconciliationCaseRecord:
        case_id = f"recon_{next(self._reconciliation_counter):06d}"
        case = _ReconciliationCaseRecord(
            case_id=case_id,
            provider=provider,
            event_id=event_id,
            invoice_id=invoice_id,
            reason=reason,
            status="open",
            created_at=created_at,
        )
        self._reconciliation_cases[case_id] = case
        return case

    def _record_payout_if_settled(
        self,
        *,
        record: _InvoiceRecord,
        amount: float,
        provider: str,
        destination_label: str,
        settled_at: datetime,
    ) -> None:
        if amount <= 0:
            return
        payout_id = f"payout_{next(self._payout_counter):06d}"
        status = "settled" if record.balance_due <= 0 else "in_transit"
        payout = _PayoutRecord(
            payout_id=payout_id,
            invoice_id=record.invoice_id,
            amount=self._round_amount(amount),
            currency=record.currency,
            destination_label=destination_label,
            provider=provider,
            status=status,
            created_at=settled_at,
            settled_at=settled_at if status == "settled" else None,
        )
        self._payouts[payout_id] = payout

    def _to_checkout_response(self, record: _PaymentCheckoutSessionRecord) -> PaymentCheckoutSessionResponse:
        return PaymentCheckoutSessionResponse(
            checkout_session_id=record.checkout_session_id,
            invoice_id=record.invoice_id,
            provider=record.provider,
            status=record.status,
            amount_due=record.amount_due,
            currency=record.currency,
            client_token=record.client_token,
            available_methods=record.available_methods,
            expires_at=record.expires_at,
        )

    def _to_reconciliation_case_item(self, record: _ReconciliationCaseRecord) -> ReconciliationCaseItem:
        return ReconciliationCaseItem(
            case_id=record.case_id,
            provider=record.provider,
            event_id=record.event_id,
            invoice_id=record.invoice_id,
            reason=record.reason,
            status=record.status,  # type: ignore[arg-type]
            created_at=record.created_at,
            resolved_at=record.resolved_at,
            resolution_note=record.resolution_note,
        )

    def _to_payout_item(self, record: _PayoutRecord) -> PayoutItem:
        return PayoutItem(
            payout_id=record.payout_id,
            invoice_id=record.invoice_id,
            amount=record.amount,
            currency=record.currency,
            destination_label=record.destination_label,
            provider=record.provider,
            status=record.status,  # type: ignore[arg-type]
            created_at=record.created_at,
            settled_at=record.settled_at,
        )

    def _masked_dispatch_targets(self, dispatch: _DispatchRecord | None) -> str | None:
        if dispatch is None:
            return None
        masked: list[str] = []
        if dispatch.recipient_email:
            masked.append(mask_contact_target(dispatch.recipient_email, "email"))
        if dispatch.recipient_phone:
            masked.append(mask_contact_target(dispatch.recipient_phone, "sms"))
        if not masked:
            return None
        return ", ".join(masked)

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

    def _to_dispatch_response(self, dispatch: _DispatchRecord, notification_state: str) -> InvoiceDispatchResponse:
        email_masked = mask_contact_target(dispatch.recipient_email, "email") if dispatch.recipient_email else None
        phone_masked = mask_contact_target(dispatch.recipient_phone, "sms") if dispatch.recipient_phone else None
        return InvoiceDispatchResponse(
            dispatch_id=dispatch.dispatch_id,
            invoice_id=dispatch.invoice_id,
            creator_id=dispatch.creator_id,
            channels=list(dispatch.channels),
            dispatched_at=dispatch.dispatched_at,
            recipient_email_masked=email_masked,
            recipient_phone_masked=phone_masked,
            creator_portal_url=dispatch.creator_portal_url,
            idempotency_key=dispatch.idempotency_key,
            notification_state=notification_state,
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
            dispatch_id=record.dispatch_id,
            dispatched_at=record.dispatched_at,
            notification_state=record.notification_state,
            last_payment_at=record.last_payment_at,
            last_reminder_at=record.last_reminder_at,
            updated_at=record.updated_at,
        )

    def _evaluate_reminder(self, record: _InvoiceRecord, now: datetime) -> _ReminderDecision:
        if record.dispatch_id is None:
            return _ReminderDecision(eligible=False, reason="not_dispatched")

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
            self._refresh_invoice_notification(record)
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

    def _refresh_invoice_notification(self, record: _InvoiceRecord) -> None:
        if record.dispatch_id is None:
            record.notification_state = "unseen"
            return
        if record.balance_due <= 0:
            record.notification_state = "fulfilled"
            return
        if record.notification_state == "unseen":
            return
        record.notification_state = "seen_unfulfilled"

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
