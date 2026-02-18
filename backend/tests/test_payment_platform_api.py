from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
from invoicing_web.config import get_settings
from invoicing_web.main import create_app


def _client() -> TestClient:
    os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
    os.environ["RUNTIME_SECRET_GUARD_MODE"] = "off"
    os.environ["CONVERSATION_WEBHOOK_SIGNATURE_MODE"] = "off"
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
    api_module.reset_runtime_state_for_tests()
    api_module.notifier_sender = api_module._create_notifier(api_module._settings)
    api_module.openclaw_sender = api_module.notifier_sender
    return TestClient(create_app())


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/v1/invoicing/admin/login", json={"password": "test-admin-pw"})
    assert resp.status_code == 200
    return resp.json()["session_token"]


def _seed_invoice(client: TestClient, invoice_id: str = "inv-pay-001", amount_due: float = 250.0) -> None:
    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={
            "invoices": [
                {
                    "invoice_id": invoice_id,
                    "creator_id": "creator-pay-001",
                    "creator_name": "Pay Creator",
                    "creator_timezone": "UTC",
                    "contact_channel": "email",
                    "contact_target": "pay@example.com",
                    "currency": "USD",
                    "amount_due": amount_due,
                    "amount_paid": 0.0,
                    "issued_at": "2026-02-01",
                    "due_date": "2026-03-01",
                    "metadata": {"source": "test"},
                }
            ]
        },
    )
    assert upsert_resp.status_code == 200


def _set_env(name: str, value: str | None) -> str | None:
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return previous


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def test_checkout_session_and_status_flow() -> None:
    client = _client()
    _seed_invoice(client, "inv-pay-100", 180.0)

    checkout_resp = client.post(
        "/api/v1/invoicing/payments/checkout-session",
        json={
            "invoice_id": "inv-pay-100",
            "payment_methods": ["apple_pay", "card", "ach"],
            "idempotency_key": "checkout-100-idempotency",
        },
    )
    assert checkout_resp.status_code == 201
    checkout = checkout_resp.json()
    assert checkout["invoice_id"] == "inv-pay-100"
    assert checkout["status"] == "requires_payment_method"
    assert checkout["provider"] == "eros_stub"
    assert checkout["available_methods"] == ["apple_pay", "card", "ach"]

    status_resp = client.get("/api/v1/invoicing/payments/invoices/inv-pay-100/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["invoice_id"] == "inv-pay-100"
    assert status_data["latest_checkout_session_id"] == checkout["checkout_session_id"]
    assert status_data["balance_due"] == 180.0


def test_webhook_success_creates_settlement_payout() -> None:
    client = _client()
    _seed_invoice(client, "inv-pay-200", 120.0)

    webhook_resp = client.post(
        "/api/v1/invoicing/payments/webhooks/stripe",
        json={
            "event_id": "wh-evt-200",
            "event_type": "payment.succeeded",
            "invoice_id": "inv-pay-200",
            "amount": 120.0,
            "status": "succeeded",
            "occurred_at": "2026-02-18T12:00:00Z",
            "metadata": {"source": "test"},
        },
    )
    assert webhook_resp.status_code == 200
    webhook_data = webhook_resp.json()
    assert webhook_data["applied"] is True
    assert webhook_data["payment_status"] == "paid"
    assert webhook_data["balance_due"] == 0.0

    admin_token = _admin_token(client)
    payouts_resp = client.get(
        "/api/v1/invoicing/admin/payouts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert payouts_resp.status_code == 200
    payouts = payouts_resp.json()["items"]
    assert len(payouts) == 1
    payout = payouts[0]
    assert payout["invoice_id"] == "inv-pay-200"
    assert payout["status"] == "settled"

    payout_detail_resp = client.get(
        f"/api/v1/invoicing/admin/payouts/{payout['payout_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert payout_detail_resp.status_code == 200
    assert payout_detail_resp.json()["invoice_id"] == "inv-pay-200"


def test_webhook_mismatch_creates_and_resolves_reconciliation_case() -> None:
    client = _client()

    webhook_resp = client.post(
        "/api/v1/invoicing/payments/webhooks/plaid",
        json={
            "event_id": "wh-evt-missing-001",
            "event_type": "payment.succeeded",
            "invoice_id": "inv-does-not-exist",
            "amount": 75.0,
            "status": "succeeded",
            "occurred_at": "2026-02-18T13:00:00Z",
            "metadata": {"source": "test"},
        },
    )
    assert webhook_resp.status_code == 200
    webhook_data = webhook_resp.json()
    assert webhook_data["applied"] is False
    case_id = webhook_data["reconciliation_case_id"]
    assert case_id

    admin_token = _admin_token(client)
    cases_resp = client.get(
        "/api/v1/invoicing/admin/reconciliation/cases",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cases_resp.status_code == 200
    cases = cases_resp.json()["items"]
    assert len(cases) == 1
    assert cases[0]["case_id"] == case_id
    assert cases[0]["status"] == "open"

    resolve_resp = client.post(
        f"/api/v1/invoicing/admin/reconciliation/cases/{case_id}/resolve",
        json={"resolution_note": "Manual verification completed."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"


def test_webhook_signature_enforced_rejects_missing_signature() -> None:
    prev_mode = _set_env("PAYMENT_WEBHOOK_SIGNATURE_MODE", "enforce")
    prev_secret = _set_env("PAYMENT_WEBHOOK_SECRET_STRIPE", "test-stripe-webhook-secret")
    try:
        client = _client()
        _seed_invoice(client, "inv-pay-signature-001", 90.0)

        webhook_resp = client.post(
            "/api/v1/invoicing/payments/webhooks/stripe",
            json={
                "event_id": "wh-evt-signature-missing",
                "event_type": "payment.succeeded",
                "invoice_id": "inv-pay-signature-001",
                "amount": 90.0,
                "status": "succeeded",
                "occurred_at": "2026-02-18T12:00:00Z",
                "metadata": {"source": "test"},
            },
        )
        assert webhook_resp.status_code == 401
        assert "invalid webhook signature" in webhook_resp.json()["detail"]
    finally:
        _restore_env("PAYMENT_WEBHOOK_SIGNATURE_MODE", prev_mode)
        _restore_env("PAYMENT_WEBHOOK_SECRET_STRIPE", prev_secret)


def test_webhook_signature_enforced_accepts_valid_signature() -> None:
    prev_mode = _set_env("PAYMENT_WEBHOOK_SIGNATURE_MODE", "enforce")
    prev_secret = _set_env("PAYMENT_WEBHOOK_SECRET_STRIPE", "test-stripe-webhook-secret")
    try:
        client = _client()
        _seed_invoice(client, "inv-pay-signature-002", 110.0)
        payload = {
            "event_id": "wh-evt-signature-valid",
            "event_type": "payment.succeeded",
            "invoice_id": "inv-pay-signature-002",
            "amount": 110.0,
            "status": "succeeded",
            "occurred_at": "2026-02-18T12:05:00Z",
            "metadata": {"source": "test"},
        }
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = hmac.new(
            b"test-stripe-webhook-secret",
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        webhook_resp = client.post(
            "/api/v1/invoicing/payments/webhooks/stripe",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": signature,
            },
        )
        assert webhook_resp.status_code == 200
        assert webhook_resp.json()["applied"] is True
    finally:
        _restore_env("PAYMENT_WEBHOOK_SIGNATURE_MODE", prev_mode)
        _restore_env("PAYMENT_WEBHOOK_SECRET_STRIPE", prev_secret)


def test_ach_endpoints_require_admin_session() -> None:
    client = _client()
    link_resp = client.post("/api/v1/invoicing/payments/ach/link-token", json={"creator_id": "creator-001"})
    assert link_resp.status_code == 401

    exchange_resp = client.post(
        "/api/v1/invoicing/payments/ach/exchange",
        json={"creator_id": "creator-001", "public_token": "public-token", "account_id": "acct-001"},
    )
    assert exchange_resp.status_code == 401
