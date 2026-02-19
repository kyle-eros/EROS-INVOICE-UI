from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
from invoicing_web.broker_tokens import create_broker_token, encode_broker_token
from invoicing_web.config import Settings
from invoicing_web.main import create_app
from invoicing_web.notifier import HttpNotifierSender, StubNotifierSender

_TEST_SETTINGS = Settings(
    admin_password="test-admin-pass",
    admin_session_secret="test-admin-secret",
    broker_token_secret="test-broker-secret",
    broker_token_default_ttl_minutes=60,
    broker_token_max_ttl_minutes=480,
    openclaw_enabled=True,
    openclaw_channel="email,sms",
)

PREFIX = "/api/v1/invoicing"


def _client() -> TestClient:
    os.environ["RUNTIME_SECRET_GUARD_MODE"] = "off"
    os.environ["CONVERSATION_WEBHOOK_SIGNATURE_MODE"] = "off"
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
    api_module.notifier_sender = StubNotifierSender(enabled=True, channel="email,sms")
    api_module.openclaw_sender = api_module.notifier_sender
    return TestClient(create_app())


def _admin_token(client: TestClient) -> str:
    """Log in as admin and return the session token."""
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.post(
            f"{PREFIX}/admin/login",
            json={"password": "test-admin-pass"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["session_token"]


def _make_broker_token(
    *,
    scopes: frozenset[str],
    ttl_minutes: int = 60,
    now: datetime | None = None,
) -> str:
    """Create and encode a broker token for testing."""
    payload = create_broker_token(
        agent_id="test-agent",
        scopes=scopes,
        secret="test-broker-secret",
        ttl_minutes=ttl_minutes,
        now=now,
    )
    return encode_broker_token(payload, secret="test-broker-secret")


# ---------------------------------------------------------------------------
# 1. Agent endpoint requires token
# ---------------------------------------------------------------------------


def test_agent_endpoint_requires_token() -> None:
    client = _client()
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.get(f"{PREFIX}/agent/reminders/summary")
    assert resp.status_code == 401
    assert "broker token required" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Agent endpoint rejects invalid token
# ---------------------------------------------------------------------------


def test_agent_endpoint_rejects_invalid_token() -> None:
    client = _client()
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.get(
            f"{PREFIX}/agent/reminders/summary",
            headers={"Authorization": "Bearer bad-token"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Agent endpoint rejects expired token
# ---------------------------------------------------------------------------


def test_agent_endpoint_rejects_expired_token() -> None:
    client = _client()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = _make_broker_token(
        scopes=frozenset({"reminders:summary"}),
        ttl_minutes=1,
        now=past,
    )
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.get(
            f"{PREFIX}/agent/reminders/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Agent endpoint rejects revoked token
# ---------------------------------------------------------------------------


def test_agent_endpoint_rejects_revoked_token() -> None:
    client = _client()
    payload = create_broker_token(
        agent_id="test-agent",
        scopes=frozenset({"reminders:summary"}),
        secret="test-broker-secret",
        ttl_minutes=60,
    )
    token = encode_broker_token(payload, secret="test-broker-secret")

    # Revoke the token via admin endpoint
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        admin_tok = _admin_token(client)
        revoke_resp = client.post(
            f"{PREFIX}/agent/tokens/revoke",
            json={"token_id": payload.token_id},
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked"] is True

        # Now use the revoked token
        resp = client.get(
            f"{PREFIX}/agent/reminders/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Agent endpoint rejects wrong scope
# ---------------------------------------------------------------------------


def test_agent_endpoint_rejects_wrong_scope() -> None:
    client = _client()
    token = _make_broker_token(scopes=frozenset({"invoices:read"}))
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.post(
            f"{PREFIX}/agent/reminders/run/once",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 401
    assert "scope" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 6. Agent endpoint succeeds with valid token
# ---------------------------------------------------------------------------


def test_agent_endpoint_success_with_valid_token() -> None:
    client = _client()
    token = _make_broker_token(scopes=frozenset({"reminders:summary"}))
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        resp = client.get(
            f"{PREFIX}/agent/reminders/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "unpaid_count" in data
    assert "overdue_count" in data
    assert "eligible_now_count" in data
    assert "escalated_count" in data


# ---------------------------------------------------------------------------
# 7. Admin creates broker token
# ---------------------------------------------------------------------------


def test_admin_creates_broker_token() -> None:
    client = _client()
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        admin_tok = _admin_token(client)
        resp = client.post(
            f"{PREFIX}/agent/tokens",
            json={
                "agent_id": "my-scheduler-agent",
                "scopes": ["reminders:summary", "invoices:read"],
            },
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "my-scheduler-agent"
    assert set(data["scopes"]) == {"reminders:summary", "invoices:read"}
    assert "token" in data
    assert "token_id" in data
    assert "expires_at" in data


# ---------------------------------------------------------------------------
# 8. Admin revokes broker token
# ---------------------------------------------------------------------------


def test_admin_revokes_broker_token() -> None:
    client = _client()
    with patch.object(api_module, "_settings", _TEST_SETTINGS):
        admin_tok = _admin_token(client)
        resp = client.post(
            f"{PREFIX}/agent/tokens/revoke",
            json={"token_id": "some-token-id-123"},
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_id"] == "some-token-id-123"
    assert data["revoked"] is True


# ---------------------------------------------------------------------------
# 9. Sender factory returns StubOpenClawSender for stub type
# ---------------------------------------------------------------------------


def test_sender_factory_stub() -> None:
    settings = Settings(
        notifier_sender_type="stub",
        notifier_enabled=True,
        notifier_channel="email,sms",
    )
    sender = api_module._create_sender(settings)
    assert isinstance(sender, StubNotifierSender)


# ---------------------------------------------------------------------------
# 10. Sender factory returns HttpOpenClawSender for http type
# ---------------------------------------------------------------------------


def test_sender_factory_http() -> None:
    settings = Settings(
        notifier_sender_type="http",
        notifier_api_base_url="https://api.notify.example.com",
        notifier_api_key="test-api-key-123",
        notifier_channel="email,sms",
        notifier_timeout_seconds=15,
    )
    sender = api_module._create_sender(settings)
    assert isinstance(sender, HttpNotifierSender)
