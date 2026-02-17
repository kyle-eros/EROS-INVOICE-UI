from __future__ import annotations

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
ContactChannel = Literal["email", "sms"]
ReminderStatus = Literal["sent", "skipped", "failed", "dry_run"]


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
    last_payment_at: datetime | None = None
    last_reminder_at: datetime | None = None
    updated_at: datetime


class InvoiceUpsertResponse(BaseModel):
    processed_count: int
    invoices: list[InvoiceRecord]


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


class ReminderRunRequest(BaseModel):
    dry_run: bool = True
    limit: int | None = Field(default=None, ge=1, le=500)
    now_override: datetime | None = None

    @field_validator("now_override")
    @classmethod
    def _normalize_override(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ReminderResult(BaseModel):
    invoice_id: str
    status: ReminderStatus
    reason: str
    attempted_at: datetime | None = None
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_eligible_at: datetime | None = None
    contact_target_masked: str | None = None


class ReminderRunResponse(BaseModel):
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
