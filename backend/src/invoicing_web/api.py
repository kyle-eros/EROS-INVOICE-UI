from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .config import get_settings
from .models import (
    ArtifactListResponse,
    ConfirmResponse,
    EscalationListResponse,
    InvoiceUpsertRequest,
    InvoiceUpsertResponse,
    PaymentEventRequest,
    PaymentEventResponse,
    PreviewRequest,
    PreviewResponse,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderSummaryResponse,
    RunOnceResponse,
    TaskDetail,
    TaskSummary,
)
from .openclaw import StubOpenClawSender
from .store import InMemoryTaskStore, InvoiceNotFoundError, TaskNotFoundError

_settings = get_settings()
router = APIRouter(prefix=f"{_settings.api_prefix}/invoicing", tags=["invoicing"])
task_store = InMemoryTaskStore()
openclaw_sender = StubOpenClawSender(enabled=_settings.openclaw_enabled, channel=_settings.openclaw_channel)


@router.post("/preview", response_model=PreviewResponse, status_code=status.HTTP_201_CREATED)
def preview_invoice(payload: PreviewRequest) -> PreviewResponse:
    record = task_store.create_preview(payload)
    return PreviewResponse(
        task_id=record.task_id,
        status=record.status,
        agent_slug=record.payload.agent_slug,
        mode=record.payload.mode,
        window_start=record.payload.window_start,
        window_end=record.payload.window_end,
        source_count=len(record.payload.source_refs),
        created_at=record.created_at,
    )


@router.post("/confirm/{task_id}", response_model=ConfirmResponse)
def confirm_invoice(task_id: str) -> ConfirmResponse:
    try:
        record = task_store.confirm(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc
    return ConfirmResponse(task_id=record.task_id, status=record.status)


@router.post("/run/once", response_model=RunOnceResponse)
def run_once() -> RunOnceResponse:
    task_ids = task_store.run_once()
    return RunOnceResponse(processed_count=len(task_ids), task_ids=task_ids)


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks() -> list[TaskSummary]:
    return task_store.list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: str) -> TaskDetail:
    try:
        return task_store.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc


@router.get("/artifacts/{task_id}", response_model=ArtifactListResponse)
def get_artifacts(task_id: str) -> ArtifactListResponse:
    try:
        return task_store.get_artifacts(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc


@router.post("/invoices/upsert", response_model=InvoiceUpsertResponse)
def upsert_invoices(payload: InvoiceUpsertRequest) -> InvoiceUpsertResponse:
    records = task_store.upsert_invoices(payload)
    return InvoiceUpsertResponse(processed_count=len(records), invoices=records)


@router.post("/payments/events", response_model=PaymentEventResponse)
def ingest_payment_event(payload: PaymentEventRequest) -> PaymentEventResponse:
    try:
        return task_store.apply_payment_event(payload)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found: {payload.invoice_id}") from exc


@router.get("/reminders/summary", response_model=ReminderSummaryResponse)
def get_reminder_summary() -> ReminderSummaryResponse:
    return task_store.get_reminder_summary()


@router.post("/reminders/run/once", response_model=ReminderRunResponse)
def run_reminders_once(payload: ReminderRunRequest | None = None) -> ReminderRunResponse:
    request_payload = payload or ReminderRunRequest(dry_run=_settings.openclaw_dry_run_default)
    return task_store.run_reminders(request_payload, openclaw_sender)


@router.get("/reminders/escalations", response_model=EscalationListResponse)
def get_reminder_escalations() -> EscalationListResponse:
    return EscalationListResponse(items=task_store.list_escalations())
