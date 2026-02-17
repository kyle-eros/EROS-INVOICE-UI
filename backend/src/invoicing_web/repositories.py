from __future__ import annotations

from typing import Protocol

from .models import (
    EscalationItem,
    InvoiceRecord,
    InvoiceUpsertRequest,
    PaymentEventRequest,
    PaymentEventResponse,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderSummaryResponse,
)
from .openclaw import OpenClawSender


class InvoiceRepository(Protocol):
    def upsert_invoices(self, payload: InvoiceUpsertRequest) -> list[InvoiceRecord]: ...

    def apply_payment_event(self, payload: PaymentEventRequest) -> PaymentEventResponse: ...

    def list_invoices(self) -> list[InvoiceRecord]: ...


class ReminderRepository(Protocol):
    def run_reminders(self, payload: ReminderRunRequest, sender: OpenClawSender) -> ReminderRunResponse: ...

    def get_reminder_summary(self) -> ReminderSummaryResponse: ...

    def list_escalations(self) -> list[EscalationItem]: ...
