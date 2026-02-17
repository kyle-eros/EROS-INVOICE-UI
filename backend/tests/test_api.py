from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
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


def _client() -> TestClient:
    api_module.task_store.reset()
    api_module.openclaw_sender = StubOpenClawSender(enabled=True, channel="email")
    return TestClient(create_app())


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
    assert "source_ref_1=/tmp/exports/invoices_feb.csv" in artifacts_data["artifacts"][0]["content"]
    assert "metadata.legacy_command=preview-invoicing" in artifacts_data["artifacts"][0]["content"]


def test_preview_idempotency_returns_existing_task() -> None:
    client = _client()

    first = client.post("/api/v1/invoicing/preview", json=_preview_payload())
    second = client.post("/api/v1/invoicing/preview", json=_preview_payload())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] == second.json()["task_id"] == "task-0001"
    list_resp = client.get("/api/v1/invoicing/tasks")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_missing_task_returns_404() -> None:
    client = _client()

    get_task_resp = client.get("/api/v1/invoicing/tasks/task-9999")
    assert get_task_resp.status_code == 404

    confirm_resp = client.post("/api/v1/invoicing/confirm/task-9999")
    assert confirm_resp.status_code == 404

    artifacts_resp = client.get("/api/v1/invoicing/artifacts/task-9999")
    assert artifacts_resp.status_code == 404


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


def test_reminder_run_and_escalation_flow() -> None:
    client = _client()

    upsert_resp = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={"invoices": [_invoice_payload(invoice_id="inv-100", due_date="2026-02-10")]},
    )
    assert upsert_resp.status_code == 200

    dry_run_resp = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={"dry_run": True, "now_override": "2026-02-10T00:00:00Z"},
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
            json={"dry_run": False, "now_override": run_at.isoformat().replace("+00:00", "Z")},
        )
        assert live_resp.status_code == 200
        live_data = live_resp.json()
        assert live_data["failed_count"] == 0
        if index < 6:
            assert live_data["sent_count"] == 1

    capped_run = client.post(
        "/api/v1/invoicing/reminders/run/once",
        json={"dry_run": False, "now_override": "2026-03-01T00:00:00Z"},
    )
    assert capped_run.status_code == 200
    capped_result = capped_run.json()["results"][0]
    assert capped_result["status"] == "skipped"
    assert capped_result["reason"] == "max_reminders_reached"

    escalations_resp = client.get("/api/v1/invoicing/reminders/escalations")
    assert escalations_resp.status_code == 200
    escalations_data = escalations_resp.json()["items"]
    assert len(escalations_data) == 1
    assert escalations_data[0]["invoice_id"] == "inv-100"
    assert escalations_data[0]["reminder_count"] == 6


def test_reminder_summary_counts() -> None:
    client = _client()

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

    summary_resp = client.get("/api/v1/invoicing/reminders/summary")
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert summary_data["unpaid_count"] == 3
    assert summary_data["overdue_count"] == 2
    assert summary_data["eligible_now_count"] == 1
    assert summary_data["escalated_count"] == 0
