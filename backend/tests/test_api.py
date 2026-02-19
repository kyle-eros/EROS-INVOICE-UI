from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from invoicing_web import api as api_module

from invoicing_web.config import Settings, get_settings, runtime_secret_issues
from invoicing_web.main import create_app
from invoicing_web.openclaw import StubOpenClawSender


def _preview_payload() -> dict:
    return {
        "agent_slug": "payout-reconciliation",
        "window_start": "2026-02-01",
        "window_end": "2026-02-28",
        "source_refs": [
            "/tmp/exports/invoices_feb.csv",
            "/tmp/exports/chargebacks_feb.csv",
        ],
        "mode": "plan_only",
        "idempotency_key": "invoicing-feb-2026",
        "principal_employee_id": "employee-123",
        "metadata": {"legacy_command": "preview-invoicing"},
    }


def _invoice_payload(
    *,
    invoice_id: str,
    due_date: str,
    opt_out: bool = False,
    contact_target: str = "ops@example.com",
    issued_at: str = "2026-02-01",
) -> dict:
    return {
        "invoice_id": invoice_id,
        "creator_id": "creator-001",
        "creator_name": "Creator Prime",
        "creator_timezone": "UTC",
        "contact_channel": "email",
        "contact_target": contact_target,
        "currency": "USD",
        "amount_due": 250.0,
        "amount_paid": 0.0,
        "issued_at": issued_at,
        "due_date": due_date,
        "opt_out": opt_out,
        "metadata": {"source": "test"},
    }


def _invoice_detail_payload(*, gross_total: float = 500.0, split_percent: float = 50.0) -> dict:
    return {
        "service_description": "Account Management/Marketing",
        "payment_method_label": "Zelle/ACH Direct Deposit",
        "payment_instructions": {
            "zelle_account_number": "609-969-0562",
            "direct_deposit_account_number": "867595156",
            "direct_deposit_routing_number": "061092387",
        },
        "line_items": [
            {
                "platform": "OnlyFans",
                "period_start": "2025-10-01",
                "period_end": "2025-10-31",
                "line_label": "Grace Bennett (Paid)",
                "gross_total": gross_total,
                "split_percent": split_percent,
            }
        ],
    }


def _dispatch_payload(*, invoice_id: str, dispatch_time: str, idempotency_key: str = "dispatch-key-001") -> dict:
    return {
        "invoice_id": invoice_id,
        "dispatched_at": dispatch_time,
        "channels": ["email", "sms"],
        "recipient_email": "kyle@erosops.com",
        "recipient_phone": "+15555550123",
        "idempotency_key": idempotency_key,
    }


def _client() -> TestClient:
    os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
    os.environ["REMINDER_ALLOW_LIVE_NOW_OVERRIDE"] = "true"
    os.environ["RUNTIME_SECRET_GUARD_MODE"] = "off"
    os.environ["CONVERSATION_WEBHOOK_SIGNATURE_MODE"] = "off"
    os.environ["PAYMENT_WEBHOOK_SIGNATURE_MODE"] = "off"
    from invoicing_web.config import get_settings
    api_module._settings = get_settings()
    api_module.task_store = api_module.create_task_store(
        backend=api_module._settings.invoice_store_backend,
        database_url=api_module._settings.database_url,
    )
    api_module.auth_repo = api_module._create_auth_repo(api_module._settings)
    api_module.reminder_run_repo = api_module.create_reminder_run_repository(
        backend=api_module._settings.reminder_store_backend,
        database_url=api_module._settings.database_url,
    )
    api_module.reminder_workflow = api_module.ReminderWorkflowService(
        repository=api_module.reminder_run_repo,
        store=api_module.task_store,
    )
    api_module.reset_runtime_state_for_tests()
    api_module.openclaw_sender = StubOpenClawSender(enabled=True, channel="email,sms")
    return TestClient(create_app())


def _admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/invoicing/admin/login", json={"password": "test-admin-pw"})
    assert login.status_code == 200
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_invoicing_lifecycle() -> None:
    client = _client()

    preview = client.post("/api/v1/invoicing/preview", json=_preview_payload())
    assert preview.status_code == 201
    preview_data = preview.json()
    assert preview_data["task_id"] == "task-0001"
    assert preview_data["status"] == "previewed"
    assert preview_data["agent_slug"] == "payout-reconciliation"
    assert preview_data["mode"] == "plan_only"
    assert preview_data["window_start"] == "2026-02-01"
    assert preview_data["window_end"] == "2026-02-28"
    assert preview_data["source_count"] == 2
    task_id = preview_data["task_id"]

    list_resp = client.get("/api/v1/invoicing/tasks")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert len(list_data) == 1
    assert list_data[0]["task_id"] == task_id
    assert list_data[0]["agent_slug"] == "payout-reconciliation"
    assert list_data[0]["mode"] == "plan_only"
    assert list_data[0]["source_count"] == 2

    detail_resp = client.get(f"/api/v1/invoicing/tasks/{task_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["status"] == "previewed"
    assert detail_data["agent_slug"] == "payout-reconciliation"
    assert detail_data["source_refs"] == [
        "/tmp/exports/invoices_feb.csv",
        "/tmp/exports/chargebacks_feb.csv",
    ]
    assert detail_data["idempotency_key"] == "invoicing-feb-2026"

    confirm_resp = client.post(f"/api/v1/invoicing/confirm/{task_id}")
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "confirmed"

    run_resp = client.post("/api/v1/invoicing/run/once")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["processed_count"] == 1
    assert run_data["task_ids"] == [task_id]

    completed_resp = client.get(f"/api/v1/invoicing/tasks/{task_id}")
    assert completed_resp.status_code == 200
    assert completed_resp.json()["status"] == "completed"

    artifacts_resp = client.get(f"/api/v1/invoicing/artifacts/{task_id}")
    assert artifacts_resp.status_code == 200
    artifacts_data = artifacts_resp.json()
    assert artifacts_data["task_id"] == task_id
    assert len(artifacts_data["artifacts"]) == 1
    assert artifacts_data["artifacts"][0]["filename"] == f"invoicing-task-{task_id}.txt"
    assert "agent_slug=payout-reconciliation" in artifacts_data["artifacts"][0]["content"]


def test_preview_idempotency_returns_existing_task() -> None:
    client = _client()

    first = client.post("/api/v1/invoicing/preview", json=_preview_payload())
    second = client.post("/api/v1/invoicing/preview", json=_preview_payload())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] == second.json()["task_id"] == "task-0001"


def test_invoice_upsert_and_payment_event_idempotency() -> None:
    client = _client()

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-001", due_date="2026-03-01")]},
    )
    assert upsert_resp.status_code == 200
    upsert_data = upsert_resp.json()
    assert upsert_data["processed_count"] == 1
    assert upsert_data["invoices"][0]["status"] == "open"
    assert upsert_data["invoices"][0]["balance_due"] == 250.0

    payment_payload = {
        "event_id": "evt-001",
        "invoice_id": "inv-001",
        "amount": 100.0,
        "paid_at": "2026-02-15T10:30:00Z",
        "source": "bank-transfer",
        "metadata": {"batch": "feb-15"},
    }

    first_payment = client.post("/api/v1/invoicing/payments/events", json=payment_payload)
    assert first_payment.status_code == 200
    assert first_payment.json()["applied"] is True
    assert first_payment.json()["balance_due"] == 150.0

    duplicate_payment = client.post("/api/v1/invoicing/payments/events", json=payment_payload)
    assert duplicate_payment.status_code == 200
    assert duplicate_payment.json()["applied"] is False
    assert duplicate_payment.json()["balance_due"] == 150.0


def test_invoice_upsert_detail_total_validation() -> None:
    client = _client()

    valid_payload = _invoice_payload(invoice_id="inv-detail-ok", due_date="2026-03-01")
    valid_payload["detail"] = _invoice_detail_payload()
    valid_upsert = client.post("/api/v1/invoicing/invoices/upsert", json={"invoices": [valid_payload]})
    assert valid_upsert.status_code == 200

    invalid_payload = _invoice_payload(invoice_id="inv-detail-bad", due_date="2026-03-01")
    invalid_payload["detail"] = _invoice_detail_payload(gross_total=100.0, split_percent=50.0)
    invalid_upsert = client.post("/api/v1/invoicing/invoices/upsert", json={"invoices": [invalid_payload]})
    assert invalid_upsert.status_code == 422


def test_dispatch_and_acknowledge_flow() -> None:
    client = _client()

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-creator-001", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200

    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-creator-001", dispatch_time="2026-02-10T00:00:00Z"),
    )
    assert dispatch_resp.status_code == 200
    dispatch_data = dispatch_resp.json()
    assert dispatch_data["invoice_id"] == "inv-creator-001"
    assert dispatch_data["notification_state"] == "unseen"
    assert dispatch_data["recipient_email_masked"] == "k***@erosops.com"
    assert dispatch_data["recipient_phone_masked"] == "***0123"

    ack_resp = client.post(f"/api/v1/invoicing/invoices/dispatch/{dispatch_data['dispatch_id']}/ack")
    assert ack_resp.status_code == 200
    assert ack_resp.json()["notification_state"] == "seen_unfulfilled"

    payment_resp = client.post(
        "/api/v1/invoicing/payments/events",
        json={
            "event_id": "evt-creator-001",
            "invoice_id": "inv-creator-001",
            "amount": 250.0,
            "paid_at": "2026-02-15T10:30:00Z",
            "source": "bank-transfer",
            "metadata": {"batch": "settle"},
        },
    )
    assert payment_resp.status_code == 200
    assert payment_resp.json()["status"] == "paid"


def test_reminder_requires_dispatch_and_run_idempotency() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-rem-001", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200

    no_dispatch_run = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "reminder-run-0001",
        },
        headers=admin_headers,
    )
    assert no_dispatch_run.status_code == 200
    no_dispatch_data = no_dispatch_run.json()
    assert no_dispatch_data["eligible_count"] == 0
    assert no_dispatch_data["results"][0]["reason"] == "not_dispatched"

    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-rem-001", dispatch_time="2026-02-10T00:00:00Z", idempotency_key="dispatch-key-002"),
    )
    assert dispatch_resp.status_code == 200

    first_live = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "reminder-run-live-001",
        },
        headers=admin_headers,
    )
    assert first_live.status_code == 200
    first_data = first_live.json()
    assert first_data["sent_count"] == 1

    second_live_same_idem = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "reminder-run-live-001",
        },
        headers=admin_headers,
    )
    assert second_live_same_idem.status_code == 200
    second_data = second_live_same_idem.json()
    assert second_data == first_data


def test_reminder_run_and_escalation_flow() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-100", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200

    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-100", dispatch_time="2026-02-10T00:00:00Z", idempotency_key="dispatch-key-100"),
    )
    assert dispatch_resp.status_code == 200

    dry_run_resp = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={"dry_run": True, "now_override": "2026-02-10T00:00:00Z"},
        headers=admin_headers,
    )
    assert dry_run_resp.status_code == 200
    dry_run_data = dry_run_resp.json()
    assert dry_run_data["eligible_count"] == 1
    assert dry_run_data["sent_count"] == 0
    assert dry_run_data["results"][0]["status"] == "dry_run"

    first_send_at = datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc)
    for index in range(6):
        run_at = first_send_at + timedelta(hours=48 * index)
        live_resp = client.post(
            "/api/v1/invoicing/reminders/run/once",
            json={
                "dry_run": False,
                "now_override": run_at.isoformat().replace("+00:00", "Z"),
                "idempotency_key": f"reminder-loop-{index:02d}",
            },
            headers=admin_headers,
        )
        assert live_resp.status_code == 200
        live_data = live_resp.json()
        assert live_data["failed_count"] == 0
        assert live_data["sent_count"] == 1

    capped_run = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-03-01T00:00:00Z",
            "idempotency_key": "reminder-loop-cap-001",
        },
        headers=admin_headers,
    )
    assert capped_run.status_code == 200
    capped_result = capped_run.json()["results"][0]
    assert capped_result["status"] == "skipped"
    assert capped_result["reason"] == "max_reminders_reached"

    escalations_resp = client.get("/api/v1/invoicing/reminders/escalations", headers=admin_headers)
    assert escalations_resp.status_code == 200
    escalations_data = escalations_resp.json()["items"]
    assert len(escalations_data) == 1
    assert escalations_data[0]["invoice_id"] == "inv-100"
    assert escalations_data[0]["reminder_count"] == 6


def test_reminder_summary_counts() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={
            "invoices": [
                _invoice_payload(invoice_id="inv-past", due_date="2020-01-01", issued_at="2019-12-01"),
                _invoice_payload(invoice_id="inv-future", due_date="2099-01-01", issued_at="2098-12-01"),
                _invoice_payload(
                    invoice_id="inv-optout",
                    due_date="2020-01-01",
                    opt_out=True,
                    issued_at="2019-12-01",
                ),
            ]
        },
    )
    assert upsert_resp.status_code == 200

    first_dispatch = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-past", dispatch_time="2026-02-10T00:00:00Z", idempotency_key="dispatch-summary-1"),
    )
    assert first_dispatch.status_code == 200

    second_dispatch = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-optout", dispatch_time="2026-02-10T00:00:00Z", idempotency_key="dispatch-summary-2"),
    )
    assert second_dispatch.status_code == 200

    summary_resp = client.get("/api/v1/invoicing/reminders/summary", headers=admin_headers)
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert summary_data["unpaid_count"] == 3
    assert summary_data["overdue_count"] == 2
    assert summary_data["eligible_now_count"] == 1
    assert summary_data["escalated_count"] == 0


def test_runtime_secret_guard_is_provider_aware_for_conversation_enforce_mode() -> None:
    base = Settings(
        admin_password="prod-admin-password-001",
        admin_session_secret="prod-admin-secret-001",
        creator_session_secret="prod-creator-secret-001",
        broker_token_secret="prod-broker-secret-001",
        creator_magic_link_secret="prod-creator-magic-secret-001",
        conversation_enabled=True,
        conversation_webhook_signature_mode="enforce",
        conversation_provider_twilio_enabled=False,
        conversation_provider_sendgrid_enabled=False,
        conversation_provider_bluebubbles_enabled=False,
    )
    assert runtime_secret_issues(base) == ()

    with_twilio = replace(base, conversation_provider_twilio_enabled=True)
    issues = runtime_secret_issues(with_twilio)
    assert any("TWILIO_AUTH_TOKEN" in issue for issue in issues)

    with_sendgrid = replace(base, conversation_provider_sendgrid_enabled=True)
    issues = runtime_secret_issues(with_sendgrid)
    assert any("SENDGRID_INBOUND_SECRET" in issue for issue in issues)

    with_bluebubbles = replace(base, conversation_provider_bluebubbles_enabled=True)
    issues = runtime_secret_issues(with_bluebubbles)
    assert any("BLUEBUBBLES_WEBHOOK_SECRET" in issue for issue in issues)


def test_reminder_endpoints_require_admin_session() -> None:
    client = _client()

    assert client.get("/api/v1/invoicing/reminders/summary").status_code == 401
    assert client.get("/api/v1/invoicing/reminders/escalations").status_code == 401
    assert client.post("/api/v1/invoicing/reminders/run/once", json={"dry_run": True}).status_code == 401
    assert client.post("/api/v1/invoicing/reminders/evaluate", json={}).status_code == 401
    assert client.post("/api/v1/invoicing/reminders/runs/rrun_missing/send", json={}).status_code == 401


def test_admin_runtime_security_endpoint() -> None:
    client = _client()
    headers = _admin_headers(client)

    resp = client.get("/api/v1/invoicing/admin/runtime/security", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "runtime_secret_guard_mode" in body
    assert "providers_enabled" in body
    assert set(body["providers_enabled"].keys()) == {"twilio", "sendgrid", "bluebubbles"}
    assert isinstance(body["runtime_secret_issues"], list)


def test_live_reminder_requires_idempotency_key() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-idem-req", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200
    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(invoice_id="inv-idem-req", dispatch_time="2026-02-10T00:00:00Z", idempotency_key="dispatch-key-idem-req"),
    )
    assert dispatch_resp.status_code == 200

    run_resp = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={"dry_run": False},
        headers=admin_headers,
    )
    assert run_resp.status_code == 400
    assert "idempotency_key" in run_resp.json()["detail"]


def test_failed_live_attempt_enforces_cooldown() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-fail-cooldown", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200
    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json={
            "invoice_id": "inv-fail-cooldown",
            "dispatched_at": "2026-02-10T00:00:00Z",
            "channels": ["email", "sms"],
            "recipient_email": "fail@example.com",
            "recipient_phone": "+15555550123",
            "idempotency_key": "dispatch-fail-cooldown",
        },
    )
    assert dispatch_resp.status_code == 200

    first_live = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "run-fail-cooldown-1",
        },
        headers=admin_headers,
    )
    assert first_live.status_code == 200
    assert first_live.json()["failed_count"] == 1

    second_live = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:01:00Z",
            "idempotency_key": "run-fail-cooldown-2",
        },
        headers=admin_headers,
    )
    assert second_live.status_code == 200
    result = second_live.json()["results"][0]
    assert result["status"] == "skipped"
    assert result["reason"] == "cooldown_active"


def test_reminder_evaluate_then_send_flow() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-eval-send-001", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200
    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(
            invoice_id="inv-eval-send-001",
            dispatch_time="2026-02-10T00:00:00Z",
            idempotency_key="dispatch-eval-send-001",
        ),
    )
    assert dispatch_resp.status_code == 200

    eval_resp = client.post(
        "/api/v1/invoicing/reminders/evaluate",
        json={"now_override": "2026-02-10T00:00:00Z"},
        headers=admin_headers,
    )
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["run_id"] is not None
    assert eval_data["dry_run"] is True
    assert eval_data["eligible_count"] == 1

    run_id = eval_data["run_id"]
    send_resp = client.post(
        f"/api/v1/invoicing/reminders/runs/{run_id}/send",
        headers=admin_headers,
    )
    assert send_resp.status_code == 200
    send_data = send_resp.json()
    assert send_data["run_id"] == run_id
    assert send_data["dry_run"] is False
    assert send_data["sent_count"] == 1

    # Re-sending the same run should not double-process attempts.
    resend_resp = client.post(
        f"/api/v1/invoicing/reminders/runs/{run_id}/send",
        headers=admin_headers,
    )
    assert resend_resp.status_code == 200
    resend_data = resend_resp.json()
    assert resend_data["run_id"] == run_id
    assert resend_data["sent_count"] == 1

    summary_resp = client.get("/api/v1/invoicing/reminders/summary", headers=admin_headers)
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["last_run_at"] is not None
    assert summary["last_run_dry_run"] is False
    assert summary["last_run_sent_count"] == 1
    assert summary["last_run_failed_count"] == 0
    assert summary["last_run_skipped_count"] >= 0


def test_send_run_retry_progresses_across_repeated_send_calls() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-retry-progress-001", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200
    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json={
            "invoice_id": "inv-retry-progress-001",
            "dispatched_at": "2026-02-10T00:00:00Z",
            "channels": ["email"],
            "recipient_email": "fail@example.com",
            "idempotency_key": "dispatch-retry-progress-001",
        },
    )
    assert dispatch_resp.status_code == 200

    eval_resp = client.post(
        "/api/v1/invoicing/reminders/evaluate",
        json={"now_override": "2026-02-10T00:00:00Z"},
        headers=admin_headers,
    )
    assert eval_resp.status_code == 200
    run_id = eval_resp.json()["run_id"]
    assert run_id is not None

    first_send = client.post(
        f"/api/v1/invoicing/reminders/runs/{run_id}/send",
        headers=admin_headers,
    )
    assert first_send.status_code == 200
    outbox_after_first = api_module.reminder_run_repo.list_outbox_messages(run_id)
    assert len(outbox_after_first) == 1
    assert outbox_after_first[0].tries == 1
    assert outbox_after_first[0].status == "pending"
    assert outbox_after_first[0].available_at > datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc)

    # Fast-forward availability in in-memory outbox so the next send call can claim it.
    in_memory_outbox = getattr(api_module.reminder_run_repo, "_outbox", None)
    if isinstance(in_memory_outbox, dict):
        row = in_memory_outbox[outbox_after_first[0].outbox_id]
        in_memory_outbox[outbox_after_first[0].outbox_id] = row.__class__(
            **{
                **row.__dict__,
                "available_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            }
        )

    second_send = client.post(
        f"/api/v1/invoicing/reminders/runs/{run_id}/send",
        headers=admin_headers,
    )
    assert second_send.status_code == 200
    outbox_after_second = api_module.reminder_run_repo.list_outbox_messages(run_id)
    assert len(outbox_after_second) == 1
    assert outbox_after_second[0].tries == 2


def test_live_run_idempotency_conflict_returns_409() -> None:
    client = _client()
    admin_headers = _admin_headers(client)

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-idem-conflict-001", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200
    dispatch_resp = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json=_dispatch_payload(
            invoice_id="inv-idem-conflict-001",
            dispatch_time="2026-02-10T00:00:00Z",
            idempotency_key="dispatch-idem-conflict-001",
        ),
    )
    assert dispatch_resp.status_code == 200

    first = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "run-idem-conflict-001",
        },
        headers=admin_headers,
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={
            "dry_run": False,
            "now_override": "2026-02-12T00:00:00Z",
            "idempotency_key": "run-idem-conflict-001",
        },
        headers=admin_headers,
    )
    assert second.status_code == 409


def test_reminder_idempotency_persists_with_database_backend() -> None:
    original_backend = os.environ.get("REMINDER_STORE_BACKEND")
    original_database_url = os.environ.get("DATABASE_URL")
    db_name = f"/tmp/invoicing_reminder_{uuid4().hex}.db"
    try:
        os.environ["REMINDER_STORE_BACKEND"] = "postgres"
        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_name}"
        client = _client()
        admin_headers = _admin_headers(client)

        upsert_resp = client.post(
            "/api/v1/invoicing/invoices/upsert",
            json={"invoices": [_invoice_payload(invoice_id="inv-idem-db-001", due_date="2026-02-10")]},
        )
        assert upsert_resp.status_code == 200
        dispatch_resp = client.post(
            "/api/v1/invoicing/invoices/dispatch",
            json=_dispatch_payload(
                invoice_id="inv-idem-db-001",
                dispatch_time="2026-02-10T00:00:00Z",
                idempotency_key="dispatch-idem-db-001",
            ),
        )
        assert dispatch_resp.status_code == 200

        payload = {
            "dry_run": False,
            "now_override": "2026-02-10T00:00:00Z",
            "idempotency_key": "run-idem-db-001",
        }
        first = client.post(
            "/api/v1/invoicing/reminders/run/once",
            json=payload,
            headers=admin_headers,
        )
        assert first.status_code == 200
        first_data = first.json()

        # Simulate process restart with lost in-memory invoice state.
        from invoicing_web.config import get_settings
        api_module._settings = get_settings()
        api_module.auth_repo = api_module._create_auth_repo(api_module._settings)
        api_module.reminder_run_repo = api_module.create_reminder_run_repository(
            backend=api_module._settings.reminder_store_backend,
            database_url=api_module._settings.database_url,
        )
        api_module.reminder_workflow = api_module.ReminderWorkflowService(
            repository=api_module.reminder_run_repo,
            store=api_module.task_store,
        )
        api_module.task_store.reset()
        restarted_client = TestClient(create_app())

        second = restarted_client.post(
            "/api/v1/invoicing/reminders/run/once",
            json=payload,
            headers=admin_headers,
        )
        assert second.status_code == 200
        assert second.json() == first_data
    finally:
        if original_backend is None:
            os.environ.pop("REMINDER_STORE_BACKEND", None)
        else:
            os.environ["REMINDER_STORE_BACKEND"] = original_backend
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url


def test_invoice_state_persists_with_database_backend() -> None:
    from invoicing_web.task_store_backends import SQLALCHEMY_AVAILABLE as INVOICE_SQLALCHEMY_AVAILABLE

    if not INVOICE_SQLALCHEMY_AVAILABLE:
        return

    original_invoice_backend = os.environ.get("INVOICE_STORE_BACKEND")
    original_database_url = os.environ.get("DATABASE_URL")
    db_name = f"/tmp/invoicing_invoice_{uuid4().hex}.db"
    try:
        os.environ["INVOICE_STORE_BACKEND"] = "postgres"
        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_name}"
        client = _client()

        upsert_resp = client.post(
            "/api/v1/invoicing/invoices/upsert",
            json={
                "invoices": [
                    _invoice_payload(
                        invoice_id="inv-persist-jan-001",
                        due_date="2026-01-20",
                        issued_at="2026-01-05",
                    ),
                    _invoice_payload(
                        invoice_id="inv-persist-feb-001",
                        due_date="2026-02-20",
                        issued_at="2026-02-05",
                    ),
                ]
            },
        )
        assert upsert_resp.status_code == 200

        dispatch_resp = client.post(
            "/api/v1/invoicing/invoices/dispatch",
            json=_dispatch_payload(
                invoice_id="inv-persist-feb-001",
                dispatch_time="2026-02-06T00:00:00Z",
                idempotency_key="dispatch-persist-feb-001",
            ),
        )
        assert dispatch_resp.status_code == 200

        from invoicing_web.config import get_settings

        api_module._settings = get_settings()
        api_module.task_store = api_module.create_task_store(
            backend=api_module._settings.invoice_store_backend,
            database_url=api_module._settings.database_url,
        )
        api_module.auth_repo = api_module._create_auth_repo(api_module._settings)
        api_module.reminder_run_repo = api_module.create_reminder_run_repository(
            backend=api_module._settings.reminder_store_backend,
            database_url=api_module._settings.database_url,
        )
        api_module.reminder_workflow = api_module.ReminderWorkflowService(
            repository=api_module.reminder_run_repo,
            store=api_module.task_store,
        )
        api_module.conversation_repo = api_module.create_conversation_repository(
            backend=api_module._settings.conversation_store_backend,
            database_url=api_module._settings.database_url,
        )
        api_module.conversation_service = api_module.ConversationService(
            repository=api_module.conversation_repo,
            store=api_module.task_store,
            settings=api_module._settings,
        )
        restarted_client = TestClient(create_app())

        admin_headers = _admin_headers(restarted_client)
        creators_resp = restarted_client.get(
            "/api/v1/invoicing/admin/creators?focus_year=2026",
            headers=admin_headers,
        )
        assert creators_resp.status_code == 200
        items = creators_resp.json()["creators"]
        assert len(items) == 1
        assert items[0]["invoice_count"] == 2
        assert items[0]["dispatched_invoice_count"] == 1
        assert items[0]["jan_full_invoice_usd"] == 250.0
        assert items[0]["feb_current_owed_usd"] == 250.0
    finally:
        if original_invoice_backend is None:
            os.environ.pop("INVOICE_STORE_BACKEND", None)
        else:
            os.environ["INVOICE_STORE_BACKEND"] = original_invoice_backend
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
