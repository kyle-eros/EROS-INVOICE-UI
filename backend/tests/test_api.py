from __future__ import annotations

from fastapi.testclient import TestClient

from invoicing_web.api import task_store
from invoicing_web.main import create_app


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


def test_invoicing_lifecycle() -> None:
    task_store.reset()
    client = TestClient(create_app())

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
    task_store.reset()
    client = TestClient(create_app())

    first = client.post("/api/v1/invoicing/preview", json=_preview_payload())
    second = client.post("/api/v1/invoicing/preview", json=_preview_payload())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] == second.json()["task_id"] == "task-0001"
    list_resp = client.get("/api/v1/invoicing/tasks")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_missing_task_returns_404() -> None:
    task_store.reset()
    client = TestClient(create_app())

    get_task_resp = client.get("/api/v1/invoicing/tasks/task-9999")
    assert get_task_resp.status_code == 404

    confirm_resp = client.post("/api/v1/invoicing/confirm/task-9999")
    assert confirm_resp.status_code == 404

    artifacts_resp = client.get("/api/v1/invoicing/artifacts/task-9999")
    assert artifacts_resp.status_code == 404
