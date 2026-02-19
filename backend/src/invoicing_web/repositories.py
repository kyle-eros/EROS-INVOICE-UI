from __future__ import annotations

from typing import Protocol

from .models import (
    CreatorPaymentSubmissionResponse,
    CreatorDispatchAcknowledgeResponse,
    CreatorInvoicesResponse,
    InvoicePdfContext,
    InvoiceDispatchRequest,
    InvoiceDispatchResponse,
    EscalationItem,
    InvoiceRecord,
    InvoiceUpsertRequest,
    PaymentEventRequest,
    PaymentEventResponse,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderSummaryResponse,
)
from .notifier import NotifierSender


class InvoiceRepository(Protocol):
    def upsert_invoices(self, payload: InvoiceUpsertRequest) -> list[InvoiceRecord]: ...

    def dispatch_invoice(self, payload: InvoiceDispatchRequest) -> InvoiceDispatchResponse: ...

    def acknowledge_dispatch(self, dispatch_id: str) -> CreatorDispatchAcknowledgeResponse: ...

    def apply_payment_event(self, payload: PaymentEventRequest) -> PaymentEventResponse: ...

    def list_invoices(self) -> list[InvoiceRecord]: ...

    def get_creator_invoices(self, creator_id: str) -> CreatorInvoicesResponse: ...

    def get_creator_invoice_pdf(self, creator_id: str, invoice_id: str) -> InvoicePdfContext: ...

    def submit_creator_payment_submission(
        self,
        creator_id: str,
        invoice_id: str,
    ) -> CreatorPaymentSubmissionResponse: ...


class ReminderRepository(Protocol):
    def run_reminders(self, payload: ReminderRunRequest, sender: NotifierSender) -> ReminderRunResponse: ...

    def get_reminder_summary(self) -> ReminderSummaryResponse: ...

    def list_escalations(self) -> list[EscalationItem]: ...
