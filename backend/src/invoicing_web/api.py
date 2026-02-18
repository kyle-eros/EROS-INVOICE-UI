from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from .auth_store import (
    AuthStateRepository,
    InMemoryAuthStateRepository,
    SqlAlchemyAuthStateRepository,
)
from .broker_tokens import BrokerTokenError, BrokerTokenPayload, create_broker_token, decode_broker_token, encode_broker_token
from .config import Settings, get_settings
from .creator_tokens import CreatorTokenError, create_creator_token, decode_creator_token, encode_creator_token
from .models import (
    AchExchangeRequest,
    AchExchangeResponse,
    AchLinkTokenRequest,
    AchLinkTokenResponse,
    AdminCreatorDirectoryItem,
    AdminCreatorDirectoryResponse,
    AdminLoginRequest,
    AdminLoginResponse,
    ArtifactListResponse,
    BrokerTokenRequest,
    BrokerTokenResponse,
    BrokerTokenRevokeRequest,
    ConfirmResponse,
    CreatorDispatchAcknowledgeResponse,
    CreatorInvoicesResponse,
    EscalationListResponse,
    InvoiceDispatchRequest,
    InvoiceDispatchResponse,
    InvoiceRecord,
    InvoiceUpsertRequest,
    InvoiceUpsertResponse,
    PaymentCheckoutSessionRequest,
    PaymentCheckoutSessionResponse,
    PasskeyConfirmResponse,
    PasskeyGenerateRequest,
    PasskeyGenerateResponse,
    PasskeyListItem,
    PasskeyListResponse,
    PasskeyLoginRequest,
    PasskeyLookupResponse,
    PasskeyRevokeRequest,
    PasskeyRevokeResponse,
    PaymentEventRequest,
    PaymentEventResponse,
    PaymentInvoiceStatusResponse,
    PaymentWebhookEventRequest,
    PaymentWebhookEventResponse,
    PayoutItem,
    PayoutListResponse,
    PreviewRequest,
    PreviewResponse,
    ReconciliationCaseListResponse,
    ReconciliationCaseResolveRequest,
    ReconciliationCaseResolveResponse,
    ReminderRunRequest,
    ReminderRunResponse,
    ReminderSummaryResponse,
    RunOnceResponse,
    TaskDetail,
    TaskSummary,
)
from .notifier import HttpNotifierSender, NotifierSender, StubNotifierSender
from .pdf_renderer import render_invoice_pdf
from .store import (
    CreatorNotFoundError,
    DispatchNotFoundError,
    InMemoryTaskStore,
    InvoiceDetailNotFoundError,
    InvoiceNotFoundError,
    PayoutNotFoundError,
    ReconciliationCaseNotFoundError,
    TaskNotFoundError,
)

_settings = get_settings()
router = APIRouter(prefix=f"{_settings.api_prefix}/invoicing", tags=["invoicing"])
task_store = InMemoryTaskStore()


def _create_auth_repo(settings: Settings) -> AuthStateRepository:
    backend = settings.auth_store_backend.strip().lower()
    if backend == "postgres":
        return SqlAlchemyAuthStateRepository(settings.database_url)
    if backend == "inmemory":
        return InMemoryAuthStateRepository()
    raise RuntimeError(f"unsupported AUTH_STORE_BACKEND: {settings.auth_store_backend}")


def _create_notifier(settings: Settings) -> NotifierSender:
    sender_type = settings.notifier_sender_type
    if sender_type == "stub" and settings.openclaw_sender_type != "stub":
        sender_type = settings.openclaw_sender_type
    base_url = settings.notifier_api_base_url or settings.openclaw_api_base_url
    api_key = settings.notifier_api_key or settings.openclaw_api_key
    channel = settings.notifier_channel or settings.openclaw_channel
    enabled = settings.notifier_enabled or settings.openclaw_enabled
    timeout_seconds = settings.notifier_timeout_seconds or settings.openclaw_timeout_seconds
    if sender_type == "http":
        return HttpNotifierSender(
            base_url=base_url,
            api_key=api_key,
            channels={ch.strip() for ch in channel.split(",") if ch.strip()},
            timeout_seconds=timeout_seconds,
        )
    return StubNotifierSender(enabled=enabled, channel=channel)


def _create_sender(settings: Settings) -> NotifierSender:
    # Backward-compatible alias for existing tests and local scripts.
    return _create_notifier(settings)


notifier_sender: NotifierSender = _create_notifier(_settings)
# Backward-compatible alias for tests and older local tooling that still patch this symbol.
openclaw_sender: NotifierSender = notifier_sender
auth_repo: AuthStateRepository = _create_auth_repo(_settings)


def _active_notifier_sender() -> NotifierSender:
    legacy_sender = globals().get("openclaw_sender")
    if legacy_sender is not None and legacy_sender is not notifier_sender:
        return legacy_sender  # type: ignore[return-value]
    return notifier_sender


def reset_runtime_state_for_tests() -> None:
    task_store.reset()
    auth_repo.reset()


def _require_admin(request: Request) -> None:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(401, "admin session required")
    try:
        payload = decode_creator_token(token, secret=_settings.admin_session_secret)
        if payload.creator_id != "__admin__":
            raise CreatorTokenError("not an admin token")
    except CreatorTokenError as exc:
        raise HTTPException(401, str(exc)) from exc


def _require_creator_session(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(401, "session required")
    try:
        payload = decode_creator_token(token, secret=_settings.creator_session_secret)
    except CreatorTokenError as exc:
        raise HTTPException(401, str(exc)) from exc
    if auth_repo.is_creator_revoked(payload.creator_id):
        raise HTTPException(401, "session revoked")
    if payload.session_version != auth_repo.current_session_version(payload.creator_id):
        raise HTTPException(401, "session revoked")
    return payload.creator_id


def _require_broker_token(request: Request, required_scope: str) -> BrokerTokenPayload:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(401, "broker token required")
    try:
        payload = decode_broker_token(token, secret=_settings.broker_token_secret, required_scope=required_scope)
    except BrokerTokenError as exc:
        raise HTTPException(401, str(exc)) from exc
    if task_store.is_broker_token_revoked(payload.token_id):
        raise HTTPException(401, "broker token revoked")
    return payload


def _client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client else "unknown"
    if not _settings.trust_proxy_headers:
        return direct_ip
    if not _settings.trusted_proxy_ips or direct_ip not in _settings.trusted_proxy_ips:
        return direct_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return direct_ip
    trusted_ip = forwarded.split(",")[0].strip()
    return trusted_ip or direct_ip


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


@router.post("/invoices/dispatch", response_model=InvoiceDispatchResponse)
def dispatch_invoice(payload: InvoiceDispatchRequest) -> InvoiceDispatchResponse:
    try:
        return task_store.dispatch_invoice(payload)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found: {payload.invoice_id}") from exc


@router.post("/invoices/dispatch/{dispatch_id}/ack", response_model=CreatorDispatchAcknowledgeResponse)
def acknowledge_dispatch(dispatch_id: str) -> CreatorDispatchAcknowledgeResponse:
    try:
        return task_store.acknowledge_dispatch(dispatch_id)
    except DispatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"dispatch not found: {dispatch_id}") from exc
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found for dispatch: {dispatch_id}") from exc


@router.post("/payments/events", response_model=PaymentEventResponse)
def ingest_payment_event(payload: PaymentEventRequest) -> PaymentEventResponse:
    try:
        return task_store.apply_payment_event(payload)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found: {payload.invoice_id}") from exc


@router.post("/payments/checkout-session", response_model=PaymentCheckoutSessionResponse, status_code=status.HTTP_201_CREATED)
def create_checkout_session(payload: PaymentCheckoutSessionRequest) -> PaymentCheckoutSessionResponse:
    try:
        return task_store.create_checkout_session(payload, provider_name=_settings.payments_provider_name)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found: {payload.invoice_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/payments/ach/link-token", response_model=AchLinkTokenResponse, status_code=status.HTTP_201_CREATED)
def create_ach_link_token(payload: AchLinkTokenRequest, request: Request) -> AchLinkTokenResponse:
    _require_admin(request)
    return task_store.create_ach_link_token(payload, provider_name=_settings.payments_provider_name)


@router.post("/payments/ach/exchange", response_model=AchExchangeResponse, status_code=status.HTTP_201_CREATED)
def exchange_ach_token(payload: AchExchangeRequest, request: Request) -> AchExchangeResponse:
    _require_admin(request)
    return task_store.exchange_ach_token(payload, provider_name=_settings.payments_provider_name)


@router.post("/payments/webhooks/{provider}", response_model=PaymentWebhookEventResponse)
def ingest_payment_webhook(provider: str, payload: PaymentWebhookEventRequest) -> PaymentWebhookEventResponse:
    normalized_provider = provider.strip().lower()
    if not normalized_provider:
        raise HTTPException(400, "provider is required")
    return task_store.apply_payment_webhook(
        normalized_provider,
        payload,
        settlement_destination_label=_settings.agency_settlement_account_label,
    )


@router.get("/payments/invoices/{invoice_id}/status", response_model=PaymentInvoiceStatusResponse)
def get_payment_invoice_status(invoice_id: str) -> PaymentInvoiceStatusResponse:
    try:
        return task_store.get_payment_invoice_status(invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"invoice not found: {invoice_id}") from exc


@router.get("/reminders/summary", response_model=ReminderSummaryResponse)
def get_reminder_summary() -> ReminderSummaryResponse:
    return task_store.get_reminder_summary()


@router.post("/reminders/run/once", response_model=ReminderRunResponse)
def run_reminders_once(payload: ReminderRunRequest | None = None) -> ReminderRunResponse:
    request_payload = payload or ReminderRunRequest(dry_run=_settings.notifier_dry_run_default)
    return task_store.run_reminders(request_payload, _active_notifier_sender())


@router.get("/reminders/escalations", response_model=EscalationListResponse)
def get_reminder_escalations() -> EscalationListResponse:
    return EscalationListResponse(items=task_store.list_escalations())


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------


@router.post("/admin/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    if not _settings.admin_password:
        raise HTTPException(503, "admin password not configured")
    if payload.password != _settings.admin_password:
        raise HTTPException(401, "invalid password")
    token_payload = create_creator_token(
        creator_id="__admin__",
        secret=_settings.admin_session_secret,
        ttl_minutes=480,
    )
    token = encode_creator_token(token_payload, secret=_settings.admin_session_secret)
    return AdminLoginResponse(
        authenticated=True,
        session_token=token,
        expires_at=token_payload.expires_at,
    )


@router.get("/admin/session")
def admin_session(request: Request) -> dict:
    _require_admin(request)
    return {"authenticated": True}


@router.get("/admin/creators", response_model=AdminCreatorDirectoryResponse)
def admin_creator_directory(request: Request) -> AdminCreatorDirectoryResponse:
    _require_admin(request)

    directory: dict[str, dict[str, int | str]] = {}
    for invoice in task_store.list_invoices():
        bucket = directory.get(invoice.creator_id)
        if bucket is None:
            bucket = {
                "creator_name": invoice.creator_name,
                "invoice_count": 0,
                "dispatched_invoice_count": 0,
            }
            directory[invoice.creator_id] = bucket
        bucket["invoice_count"] = int(bucket["invoice_count"]) + 1
        if invoice.dispatch_id is not None:
            bucket["dispatched_invoice_count"] = int(bucket["dispatched_invoice_count"]) + 1

    items = [
        AdminCreatorDirectoryItem(
            creator_id=creator_id,
            creator_name=str(values["creator_name"]),
            invoice_count=int(values["invoice_count"]),
            dispatched_invoice_count=int(values["dispatched_invoice_count"]),
            ready_for_portal=int(values["dispatched_invoice_count"]) > 0,
        )
        for creator_id, values in directory.items()
    ]
    items.sort(key=lambda item: (item.creator_name.lower(), item.creator_id))
    return AdminCreatorDirectoryResponse(creators=items)


@router.get("/admin/reconciliation/cases", response_model=ReconciliationCaseListResponse)
def list_reconciliation_cases(request: Request) -> ReconciliationCaseListResponse:
    _require_admin(request)
    return ReconciliationCaseListResponse(items=task_store.list_reconciliation_cases())


@router.post(
    "/admin/reconciliation/cases/{case_id}/resolve",
    response_model=ReconciliationCaseResolveResponse,
)
def resolve_reconciliation_case(
    case_id: str,
    payload: ReconciliationCaseResolveRequest,
    request: Request,
) -> ReconciliationCaseResolveResponse:
    _require_admin(request)
    try:
        return task_store.resolve_reconciliation_case(case_id, payload)
    except ReconciliationCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"reconciliation case not found: {case_id}") from exc


@router.get("/admin/payouts", response_model=PayoutListResponse)
def list_payouts(request: Request) -> PayoutListResponse:
    _require_admin(request)
    return task_store.list_payouts()


@router.get("/admin/payouts/{payout_id}", response_model=PayoutItem)
def get_payout(payout_id: str, request: Request) -> PayoutItem:
    _require_admin(request)
    try:
        return task_store.get_payout(payout_id)
    except PayoutNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"payout not found: {payout_id}") from exc


# ---------------------------------------------------------------------------
# Passkey management (admin-only)
# ---------------------------------------------------------------------------


@router.post("/passkeys/generate", response_model=PasskeyGenerateResponse)
def generate_passkey(payload: PasskeyGenerateRequest, request: Request) -> PasskeyGenerateResponse:
    _require_admin(request)
    record, raw_passkey = auth_repo.generate_passkey(payload.creator_id, payload.creator_name)
    return PasskeyGenerateResponse(
        creator_id=record.creator_id,
        creator_name=record.creator_name,
        passkey=raw_passkey,
        display_prefix=record.display_prefix,
        created_at=record.created_at,
    )


@router.get("/passkeys", response_model=PasskeyListResponse)
def list_passkeys(request: Request) -> PasskeyListResponse:
    _require_admin(request)
    records = auth_repo.list_passkeys()
    items = [
        PasskeyListItem(
            creator_id=r.creator_id,
            creator_name=r.creator_name,
            display_prefix=r.display_prefix,
            created_at=r.created_at,
        )
        for r in records
    ]
    return PasskeyListResponse(creators=items)


@router.post("/passkeys/revoke", response_model=PasskeyRevokeResponse)
def revoke_passkey(payload: PasskeyRevokeRequest, request: Request) -> PasskeyRevokeResponse:
    _require_admin(request)
    revoked = auth_repo.revoke_passkey(payload.creator_id)
    return PasskeyRevokeResponse(creator_id=payload.creator_id, revoked=revoked)


# ---------------------------------------------------------------------------
# Creator auth
# ---------------------------------------------------------------------------


@router.post("/auth/lookup", response_model=PasskeyLookupResponse)
def auth_lookup(payload: PasskeyLoginRequest, request: Request) -> PasskeyLookupResponse:
    ip = _client_ip(request)
    if not auth_repo.check_rate_limit(ip):
        raise HTTPException(429, "too many login attempts, try again later")
    record = auth_repo.lookup_by_passkey(payload.passkey)
    if record is None:
        auth_repo.record_failed_attempt(ip)
        raise HTTPException(401, "invalid passkey")
    return PasskeyLookupResponse(creator_id=record.creator_id, creator_name=record.creator_name)


@router.post("/auth/confirm", response_model=PasskeyConfirmResponse)
def auth_confirm(payload: PasskeyLoginRequest, request: Request) -> PasskeyConfirmResponse:
    ip = _client_ip(request)
    if not auth_repo.check_rate_limit(ip):
        raise HTTPException(429, "too many login attempts, try again later")
    record = auth_repo.lookup_by_passkey(payload.passkey)
    if record is None:
        auth_repo.record_failed_attempt(ip)
        raise HTTPException(401, "invalid passkey")
    if auth_repo.is_creator_revoked(record.creator_id):
        raise HTTPException(401, "passkey has been revoked")
    session_version = auth_repo.current_session_version(record.creator_id)
    token_payload = create_creator_token(
        creator_id=record.creator_id,
        secret=_settings.creator_session_secret,
        ttl_minutes=_settings.creator_session_ttl_minutes,
        session_version=session_version,
    )
    token = encode_creator_token(token_payload, secret=_settings.creator_session_secret)
    return PasskeyConfirmResponse(
        creator_id=record.creator_id,
        creator_name=record.creator_name,
        session_token=token,
        expires_at=token_payload.expires_at,
    )


# ---------------------------------------------------------------------------
# Session-based creator data
# ---------------------------------------------------------------------------


@router.get("/me/invoices", response_model=CreatorInvoicesResponse)
def get_my_invoices(request: Request) -> CreatorInvoicesResponse:
    creator_id = _require_creator_session(request)
    try:
        return task_store.get_creator_invoices(creator_id)
    except CreatorNotFoundError as exc:
        raise HTTPException(404, f"creator not found: {creator_id}") from exc


@router.get("/me/invoices/{invoice_id}/pdf")
def get_my_invoice_pdf(invoice_id: str, request: Request) -> Response:
    creator_id = _require_creator_session(request)
    try:
        pdf_context = task_store.get_creator_invoice_pdf(creator_id, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(404, f"invoice not found: {invoice_id}") from exc
    except InvoiceDetailNotFoundError as exc:
        raise HTTPException(422, f"invoice detail payload missing: {invoice_id}") from exc

    pdf_content = render_invoice_pdf(pdf_context)
    headers = {"Content-Disposition": f'inline; filename="{pdf_context.invoice_id}.pdf"'}
    return Response(content=pdf_content, media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# Agent endpoints (broker-token authenticated)
# ---------------------------------------------------------------------------


@router.get("/agent/reminders/summary", response_model=ReminderSummaryResponse)
def agent_reminder_summary(request: Request) -> ReminderSummaryResponse:
    _require_broker_token(request, "reminders:summary")
    return task_store.get_reminder_summary()


@router.get("/agent/invoices", response_model=list[InvoiceRecord])
def agent_list_invoices(request: Request) -> list[InvoiceRecord]:
    _require_broker_token(request, "invoices:read")
    return task_store.list_invoices()


@router.post("/agent/reminders/run/once", response_model=ReminderRunResponse)
def agent_run_reminders(request: Request, payload: ReminderRunRequest | None = None) -> ReminderRunResponse:
    _require_broker_token(request, "reminders:run")
    request_payload = payload or ReminderRunRequest(dry_run=_settings.notifier_dry_run_default)
    return task_store.run_reminders(request_payload, _active_notifier_sender())


@router.get("/agent/reminders/escalations", response_model=EscalationListResponse)
def agent_list_escalations(request: Request) -> EscalationListResponse:
    _require_broker_token(request, "reminders:read")
    return EscalationListResponse(items=task_store.list_escalations())


# ---------------------------------------------------------------------------
# Broker token management (admin-only)
# ---------------------------------------------------------------------------


@router.post("/agent/tokens", response_model=BrokerTokenResponse, status_code=status.HTTP_201_CREATED)
def create_agent_token(payload: BrokerTokenRequest, request: Request) -> BrokerTokenResponse:
    _require_admin(request)
    ttl = payload.ttl_minutes or _settings.broker_token_default_ttl_minutes
    if ttl > _settings.broker_token_max_ttl_minutes:
        raise HTTPException(400, f"ttl_minutes cannot exceed {_settings.broker_token_max_ttl_minutes}")
    token_payload = create_broker_token(
        agent_id=payload.agent_id,
        scopes=frozenset(payload.scopes),
        secret=_settings.broker_token_secret,
        ttl_minutes=ttl,
    )
    token = encode_broker_token(token_payload, secret=_settings.broker_token_secret)
    return BrokerTokenResponse(
        token=token,
        agent_id=token_payload.agent_id,
        scopes=sorted(token_payload.scopes),
        expires_at=token_payload.expires_at,
        token_id=token_payload.token_id,
    )


@router.post("/agent/tokens/revoke")
def revoke_agent_token(payload: BrokerTokenRevokeRequest, request: Request) -> dict:
    _require_admin(request)
    task_store.revoke_broker_token(payload.token_id)
    return {"token_id": payload.token_id, "revoked": True}
