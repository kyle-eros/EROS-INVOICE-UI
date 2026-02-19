from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

TaskStatus = Literal["previewed", "confirmed", "completed"]
RunMode = Literal["plan_only", "dry_run"]
FinancialAgentSlug = Literal[
    "payout-reconciliation",
    "commission-payroll",
    "chargeback-defense",
]

InvoiceStatus = Literal["open", "partial", "paid", "overdue", "escalated"]
ContactChannel = Literal["email", "sms", "imessage"]
ReminderStatus = Literal["sent", "skipped", "failed", "dry_run"]
NotificationState = Literal["unseen", "seen_unfulfilled", "fulfilled"]
PaymentMethodType = Literal["apple_pay", "card", "ach", "zelle_manual"]
PaymentIntentStatus = Literal[
    "requires_payment_method",
    "processing",
    "succeeded",
    "failed",
    "canceled",
]
ReconciliationCaseStatus = Literal["open", "resolved"]
PayoutStatus = Literal["pending", "in_transit", "settled", "failed"]
ConversationThreadStatus = Literal["open", "agent_paused", "human_handoff", "closed"]
ConversationDirection = Literal["inbound", "outbound"]
ConversationSenderType = Literal["creator", "agent", "admin", "system"]
ConversationDeliveryState = Literal["queued", "sent", "delivered", "failed", "received"]
ConversationAction = Literal["respond", "handoff", "no_reply"]

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


def _as_decimal(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value))


def compute_split_amount(gross_total: float, split_percent: float) -> Decimal:
    return (_as_decimal(gross_total) * _as_decimal(split_percent) / HUNDRED).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )


def compute_detail_split_total(line_items: list["InvoiceLineItemDetail"]) -> Decimal:
    total = Decimal("0")
    for item in line_items:
        total += compute_split_amount(item.gross_total, item.split_percent)
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)


class PreviewRequest(BaseModel):
    agent_slug: FinancialAgentSlug
    window_start: date
    window_end: date
    source_refs: list[str] = Field(min_length=1, max_length=256)
    mode: RunMode = "plan_only"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=256)
    principal_employee_id: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("source_refs")
    @classmethod
    def _normalize_source_refs(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_ref in value:
            source_ref = str(raw_ref).strip()
            if not source_ref:
                raise ValueError("source_refs entries cannot be blank")
            if source_ref in seen:
                raise ValueError("source_refs entries must be unique")
            seen.add(source_ref)
            normalized.append(source_ref)
        return normalized

    @field_validator("metadata")
    @classmethod
    def _normalize_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key).strip()
            item = str(raw_item).strip()
            if not key:
                raise ValueError("metadata keys cannot be blank")
            if not item:
                raise ValueError("metadata values cannot be blank")
            normalized[key] = item
        return normalized

    @model_validator(mode="after")
    def _validate_window(self) -> PreviewRequest:
        if self.window_end < self.window_start:
            raise ValueError("window_end must be greater than or equal to window_start")
        return self


class PreviewResponse(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_count: int
    created_at: datetime


class ConfirmResponse(BaseModel):
    task_id: str
    status: TaskStatus


class RunOnceResponse(BaseModel):
    processed_count: int
    task_ids: list[str]


class TaskSummary(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_count: int
    created_at: datetime
    updated_at: datetime


class TaskDetail(BaseModel):
    task_id: str
    status: TaskStatus
    agent_slug: FinancialAgentSlug
    mode: RunMode
    window_start: date
    window_end: date
    source_refs: list[str]
    idempotency_key: str | None = None
    principal_employee_id: str | None = None
    metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    filename: str
    content_type: str
    content: str


class ArtifactListResponse(BaseModel):
    task_id: str
    artifacts: list[Artifact]


class InvoicePaymentInstructions(BaseModel):
    zelle_account_number: str = Field(min_length=1, max_length=128)
    direct_deposit_account_number: str = Field(min_length=1, max_length=128)
    direct_deposit_routing_number: str = Field(min_length=1, max_length=128)

    @field_validator("zelle_account_number", "direct_deposit_account_number", "direct_deposit_routing_number")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("payment instruction fields cannot be blank")
        return normalized


class InvoiceLineItemDetail(BaseModel):
    platform: str = Field(min_length=1, max_length=128)
    period_start: date
    period_end: date
    line_label: str = Field(min_length=1, max_length=256)
    gross_total: float = Field(ge=0)
    split_percent: float = Field(default=50.0, gt=0, le=100)

    @field_validator("platform", "line_label")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("line item fields cannot be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_period(self) -> InvoiceLineItemDetail:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class InvoiceDetailPayload(BaseModel):
    service_description: str = Field(min_length=1, max_length=256)
    payment_method_label: str = Field(min_length=1, max_length=256)
    payment_instructions: InvoicePaymentInstructions
    line_items: list[InvoiceLineItemDetail] = Field(min_length=1, max_length=250)

    @field_validator("service_description", "payment_method_label")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("invoice detail fields cannot be blank")
        return normalized


class InvoiceUpsertItem(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=128)
    creator_id: str = Field(min_length=1, max_length=128)
    creator_name: str = Field(min_length=1, max_length=256)
    creator_timezone: str | None = Field(default=None, max_length=128)
    contact_channel: ContactChannel = "email"
    contact_target: str = Field(min_length=3, max_length=256)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    amount_due: float = Field(ge=0)
    amount_paid: float = Field(default=0, ge=0)
    issued_at: date
    due_date: date
    opt_out: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    detail: InvoiceDetailPayload | None = None

    @field_validator("invoice_id", "creator_id", "creator_name", "contact_target")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a 3-letter alphabetic code")
        return normalized

    @field_validator("creator_timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"invalid timezone: {normalized}") from exc
        return normalized

    @field_validator("metadata")
    @classmethod
    def _normalize_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key).strip()
            item = str(raw_item).strip()
            if not key:
                raise ValueError("metadata keys cannot be blank")
            if not item:
                raise ValueError("metadata values cannot be blank")
            normalized[key] = item
        return normalized

    @model_validator(mode="after")
    def _validate_amounts(self) -> InvoiceUpsertItem:
        if self.amount_paid > self.amount_due:
            raise ValueError("amount_paid cannot exceed amount_due")
        if self.due_date < self.issued_at:
            raise ValueError("due_date must be greater than or equal to issued_at")
        if self.detail is not None:
            computed_total = compute_detail_split_total(self.detail.line_items)
            expected_total = _as_decimal(self.amount_due).quantize(CENTS, rounding=ROUND_HALF_UP)
            if abs(computed_total - expected_total) > CENTS:
                raise ValueError("amount_due must match line item split total within $0.01")
        return self


class InvoiceUpsertRequest(BaseModel):
    invoices: list[InvoiceUpsertItem] = Field(min_length=1, max_length=500)


class InvoiceRecord(BaseModel):
    invoice_id: str
    creator_id: str
    creator_name: str
    creator_timezone: str | None
    contact_channel: ContactChannel
    contact_target_masked: str
    currency: str
    amount_due: float
    amount_paid: float
    balance_due: float
    issued_at: date
    due_date: date
    status: InvoiceStatus
    opt_out: bool
    reminder_count: int
    dispatch_id: str | None = None
    dispatched_at: datetime | None = None
    notification_state: NotificationState
    last_payment_at: datetime | None = None
    last_reminder_attempt_at: datetime | None = None
    last_reminder_at: datetime | None = None
    updated_at: datetime


class InvoiceUpsertResponse(BaseModel):
    processed_count: int
    invoices: list[InvoiceRecord]


class InvoiceDispatchRequest(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=128)
    dispatched_at: datetime | None = None
    channels: list[ContactChannel] = Field(min_length=1, max_length=2)
    recipient_email: str | None = Field(default=None, min_length=5, max_length=256)
    recipient_phone: str | None = Field(default=None, min_length=7, max_length=32)
    creator_portal_url: str | None = Field(default=None, max_length=2048)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("invoice_id")
    @classmethod
    def _normalize_invoice_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("invoice_id cannot be blank")
        return normalized

    @field_validator("recipient_email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("recipient_phone")
    @classmethod
    def _normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("creator_portal_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("dispatched_at")
    @classmethod
    def _normalize_dispatched_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("channels")
    @classmethod
    def _normalize_channels(cls, value: list[ContactChannel]) -> list[ContactChannel]:
        deduped: list[ContactChannel] = []
        seen: set[str] = set()
        for channel in value:
            if channel in seen:
                continue
            seen.add(channel)
            deduped.append(channel)
        return deduped

    @model_validator(mode="after")
    def _validate_recipients(self) -> InvoiceDispatchRequest:
        if "email" in self.channels and not self.recipient_email:
            raise ValueError("recipient_email is required when email channel is included")
        if ("sms" in self.channels or "imessage" in self.channels) and not self.recipient_phone:
            raise ValueError("recipient_phone is required when sms or imessage channel is included")
        return self


class InvoiceDispatchResponse(BaseModel):
    dispatch_id: str
    invoice_id: str
    creator_id: str
    channels: list[ContactChannel]
    dispatched_at: datetime
    recipient_email_masked: str | None = None
    recipient_phone_masked: str | None = None
    creator_portal_url: str | None = None
    idempotency_key: str | None = None
    notification_state: NotificationState


class PasskeyGenerateRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=128)
    creator_name: str = Field(min_length=1, max_length=256)

    @field_validator("creator_id", "creator_name")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized


class PasskeyGenerateResponse(BaseModel):
    creator_id: str
    creator_name: str
    passkey: str
    display_prefix: str
    created_at: datetime


class PasskeyListItem(BaseModel):
    creator_id: str
    creator_name: str
    display_prefix: str
    created_at: datetime


class PasskeyListResponse(BaseModel):
    creators: list[PasskeyListItem]


class AdminCreatorDirectoryItem(BaseModel):
    creator_id: str
    creator_name: str
    invoice_count: int
    dispatched_invoice_count: int
    unpaid_invoice_count: int
    submitted_payment_invoice_count: int
    total_balance_owed_usd: float
    jan_full_invoice_usd: float
    feb_current_owed_usd: float
    has_non_usd_open_invoices: bool
    ready_for_portal: bool


class AdminCreatorDirectoryResponse(BaseModel):
    creators: list[AdminCreatorDirectoryItem]


class PasskeyRevokeRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=128)


class PasskeyRevokeResponse(BaseModel):
    creator_id: str
    revoked: bool


class PasskeyLoginRequest(BaseModel):
    passkey: str = Field(min_length=1)


class PasskeyLookupResponse(BaseModel):
    creator_id: str
    creator_name: str


class PasskeyConfirmResponse(BaseModel):
    creator_id: str
    creator_name: str
    session_token: str
    expires_at: datetime


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AdminLoginResponse(BaseModel):
    authenticated: bool
    session_token: str
    expires_at: datetime


class CreatorDispatchAcknowledgeResponse(BaseModel):
    dispatch_id: str
    invoice_id: str
    creator_id: str
    notification_state: NotificationState
    acknowledged_at: datetime


class CreatorInvoiceItem(BaseModel):
    invoice_id: str
    amount_due: float
    amount_paid: float
    balance_due: float
    currency: str
    issued_at: date
    due_date: date
    status: InvoiceStatus
    dispatch_id: str
    dispatched_at: datetime
    notification_state: NotificationState
    reminder_count: int
    has_pdf: bool
    creator_payment_submitted_at: datetime | None = None
    last_reminder_attempt_at: datetime | None = None
    last_reminder_at: datetime | None = None


class CreatorInvoicesResponse(BaseModel):
    creator_id: str
    creator_name: str
    invoices: list[CreatorInvoiceItem]


class CreatorPaymentSubmissionResponse(BaseModel):
    invoice_id: str
    creator_id: str
    submitted_at: datetime
    already_submitted: bool
    status: InvoiceStatus
    balance_due: float


class InvoicePdfContext(BaseModel):
    invoice_id: str
    creator_id: str
    creator_name: str
    issued_at: date
    due_date: date
    status: InvoiceStatus
    currency: str
    amount_due: float
    amount_paid: float
    balance_due: float
    detail: InvoiceDetailPayload


class PaymentEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    invoice_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(gt=0)
    paid_at: datetime
    source: str = Field(min_length=1, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("event_id", "invoice_id", "source")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized

    @field_validator("paid_at")
    @classmethod
    def _normalize_paid_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("metadata")
    @classmethod
    def _normalize_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key).strip()
            item = str(raw_item).strip()
            if not key:
                raise ValueError("metadata keys cannot be blank")
            if not item:
                raise ValueError("metadata values cannot be blank")
            normalized[key] = item
        return normalized


class PaymentEventResponse(BaseModel):
    event_id: str
    invoice_id: str
    applied: bool
    status: InvoiceStatus
    balance_due: float


class PaymentCheckoutSessionRequest(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=128)
    payment_methods: list[PaymentMethodType] = Field(default_factory=lambda: ["apple_pay", "card", "ach"])
    return_url: str | None = Field(default=None, max_length=2048)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("invoice_id")
    @classmethod
    def _normalize_invoice_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("invoice_id cannot be blank")
        return normalized

    @field_validator("payment_methods")
    @classmethod
    def _normalize_methods(cls, value: list[PaymentMethodType]) -> list[PaymentMethodType]:
        deduped: list[PaymentMethodType] = []
        seen: set[str] = set()
        for method in value:
            if method in seen:
                continue
            seen.add(method)
            deduped.append(method)
        if not deduped:
            raise ValueError("at least one payment method is required")
        return deduped

    @field_validator("return_url")
    @classmethod
    def _normalize_return_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PaymentCheckoutSessionResponse(BaseModel):
    checkout_session_id: str
    invoice_id: str
    provider: str
    status: PaymentIntentStatus
    amount_due: float
    currency: str
    client_token: str
    available_methods: list[PaymentMethodType]
    expires_at: datetime


class AchLinkTokenRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=128)

    @field_validator("creator_id")
    @classmethod
    def _normalize_creator_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("creator_id cannot be blank")
        return normalized


class AchLinkTokenResponse(BaseModel):
    provider: str
    link_token: str
    expires_at: datetime


class AchExchangeRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=128)
    public_token: str = Field(min_length=1, max_length=512)
    account_id: str = Field(min_length=1, max_length=256)

    @field_validator("creator_id", "public_token", "account_id")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized


class AchExchangeResponse(BaseModel):
    provider: str
    payment_method_id: str
    creator_id: str
    account_mask: str
    bank_name: str
    status: PaymentIntentStatus


class PaymentWebhookEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    invoice_id: str | None = Field(default=None, max_length=128)
    amount: float | None = Field(default=None, ge=0)
    status: str = Field(min_length=1, max_length=64)
    occurred_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("event_id", "event_type", "status")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized

    @field_validator("invoice_id")
    @classmethod
    def _normalize_invoice_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("occurred_at")
    @classmethod
    def _normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("metadata")
    @classmethod
    def _normalize_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key).strip()
            item = str(raw_item).strip()
            if not key:
                raise ValueError("metadata keys cannot be blank")
            if not item:
                raise ValueError("metadata values cannot be blank")
            normalized[key] = item
        return normalized


class PaymentWebhookEventResponse(BaseModel):
    provider: str
    event_id: str
    applied: bool
    invoice_id: str | None = None
    payment_status: InvoiceStatus | None = None
    balance_due: float | None = None
    reconciliation_case_id: str | None = None


class PaymentInvoiceStatusResponse(BaseModel):
    invoice_id: str
    status: InvoiceStatus
    amount_due: float
    amount_paid: float
    balance_due: float
    currency: str
    latest_checkout_session_id: str | None = None
    latest_checkout_status: PaymentIntentStatus | None = None
    last_payment_at: datetime | None = None


class ReconciliationCaseItem(BaseModel):
    case_id: str
    provider: str
    event_id: str
    invoice_id: str | None = None
    reason: str
    status: ReconciliationCaseStatus
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ReconciliationCaseListResponse(BaseModel):
    items: list[ReconciliationCaseItem]


class ReconciliationCaseResolveRequest(BaseModel):
    resolution_note: str = Field(min_length=1, max_length=512)

    @field_validator("resolution_note")
    @classmethod
    def _normalize_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("resolution_note cannot be blank")
        return normalized


class ReconciliationCaseResolveResponse(BaseModel):
    case_id: str
    status: ReconciliationCaseStatus
    resolved_at: datetime
    resolution_note: str


class PayoutItem(BaseModel):
    payout_id: str
    invoice_id: str
    amount: float
    currency: str
    destination_label: str
    provider: str
    status: PayoutStatus
    created_at: datetime
    settled_at: datetime | None = None


class PayoutListResponse(BaseModel):
    items: list[PayoutItem]


class ReminderRunRequest(BaseModel):
    dry_run: bool = True
    limit: int | None = Field(default=None, ge=1, le=500)
    now_override: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("now_override")
    @classmethod
    def _normalize_override(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ReminderChannelResult(BaseModel):
    channel: ContactChannel
    status: ReminderStatus
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ReminderResult(BaseModel):
    invoice_id: str
    dispatch_id: str | None = None
    status: ReminderStatus
    reason: str
    attempted_at: datetime | None = None
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_eligible_at: datetime | None = None
    contact_target_masked: str | None = None
    idempotency_key: str | None = None
    channel_results: list[ReminderChannelResult] = Field(default_factory=list)


class ReminderRunResponse(BaseModel):
    run_id: str | None = None
    run_at: datetime
    dry_run: bool
    evaluated_count: int
    eligible_count: int
    sent_count: int
    failed_count: int
    skipped_count: int
    escalated_count: int
    results: list[ReminderResult]


class ReminderSummaryResponse(BaseModel):
    unpaid_count: int
    overdue_count: int
    eligible_now_count: int
    escalated_count: int
    last_run_at: datetime | None = None
    last_run_dry_run: bool | None = None
    last_run_sent_count: int | None = None
    last_run_failed_count: int | None = None
    last_run_skipped_count: int | None = None


class RuntimeSecurityStatusResponse(BaseModel):
    runtime_secret_guard_mode: Literal["off", "warn", "enforce"]
    conversation_webhook_signature_mode: Literal["off", "log_only", "enforce"]
    payment_webhook_signature_mode: Literal["off", "log_only", "enforce"]
    conversation_enabled: bool
    notifier_enabled: bool
    providers_enabled: dict[str, bool]
    runtime_secret_issues: list[str]


class ReminderEvaluateRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    now_override: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("now_override")
    @classmethod
    def _normalize_override(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ReminderSendRequest(BaseModel):
    max_messages: int | None = Field(default=None, ge=1, le=5000)


class EscalationItem(BaseModel):
    invoice_id: str
    creator_id: str
    creator_name: str
    balance_due: float
    due_date: date
    reminder_count: int
    last_reminder_at: datetime | None = None
    reason: str


class EscalationListResponse(BaseModel):
    items: list[EscalationItem]


class ConversationThreadItem(BaseModel):
    thread_id: str
    channel: ContactChannel
    external_contact_masked: str
    creator_id: str | None = None
    creator_name: str | None = None
    invoice_id: str | None = None
    status: ConversationThreadStatus
    auto_reply_count: int
    last_message_preview: str | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationThreadListResponse(BaseModel):
    items: list[ConversationThreadItem]


class ConversationMessageItem(BaseModel):
    message_id: str
    direction: ConversationDirection
    sender_type: ConversationSenderType
    body_text: str
    delivery_state: ConversationDeliveryState
    provider_message_id: str | None = None
    policy_reason: str | None = None
    created_at: datetime


class ConversationThreadDetailResponse(BaseModel):
    thread: ConversationThreadItem
    messages: list[ConversationMessageItem]


class ConversationHandoffRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConversationHandoffResponse(BaseModel):
    thread_id: str
    status: ConversationThreadStatus
    updated_at: datetime


class ConversationManualReplyRequest(BaseModel):
    body_text: str = Field(min_length=1, max_length=2000)

    @field_validator("body_text")
    @classmethod
    def _normalize_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("body_text cannot be blank")
        return normalized


class ConversationReplyResponse(BaseModel):
    thread_id: str
    message_id: str
    delivery_state: ConversationDeliveryState
    provider_message_id: str | None = None


class AgentConversationSuggestRequest(BaseModel):
    reply_text: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("reply_text")
    @classmethod
    def _normalize_reply_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reply_text cannot be blank")
        return normalized


class AgentConversationSuggestResponse(BaseModel):
    action: ConversationAction
    approved: bool
    policy_reason: str
    confidence: float


class AgentConversationExecuteRequest(BaseModel):
    action: Literal["send_reply", "handoff", "no_reply"]
    reply_text: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("reply_text")
    @classmethod
    def _normalize_reply_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AgentConversationExecuteResponse(BaseModel):
    thread_id: str
    action: Literal["send_reply", "handoff", "no_reply"]
    status: str
    message_id: str | None = None
    policy_reason: str | None = None


class ConversationInboundWebhookResponse(BaseModel):
    accepted: bool
    deduped: bool
    thread_id: str
    message_id: str | None = None


ALLOWED_BROKER_SCOPES = frozenset({
    "invoices:read",
    "reminders:read",
    "reminders:run",
    "reminders:summary",
    "conversations:read",
    "conversations:reply",
})


class BrokerTokenRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=10)
    ttl_minutes: int | None = Field(default=None, ge=1, le=480)

    @field_validator("agent_id")
    @classmethod
    def _normalize_agent_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agent_id cannot be blank")
        return normalized

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for scope in value:
            s = scope.strip()
            if not s:
                raise ValueError("scope entries cannot be blank")
            if s not in ALLOWED_BROKER_SCOPES:
                raise ValueError(f"invalid scope: {s}")
            normalized.append(s)
        return normalized


class BrokerTokenResponse(BaseModel):
    token: str
    agent_id: str
    scopes: list[str]
    expires_at: datetime
    token_id: str


class BrokerTokenRevokeRequest(BaseModel):
    token_id: str = Field(min_length=1, max_length=128)
