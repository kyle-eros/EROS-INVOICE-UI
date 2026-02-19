from __future__ import annotations

import os

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
from invoicing_web.broker_tokens import create_broker_token, encode_broker_token
from invoicing_web.main import create_app
from invoicing_web.notifier import StubNotifierSender


PREFIX = "/api/v1/invoicing"


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


def _client(*, autoreply_enabled: bool = False) -> TestClient:
    os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
    os.environ["RUNTIME_SECRET_GUARD_MODE"] = "off"
    os.environ["CONVERSATION_ENABLED"] = "true"
    os.environ["CONVERSATION_AUTOREPLY_ENABLED"] = "true" if autoreply_enabled else "false"
    os.environ.setdefault("CONVERSATION_WEBHOOK_SIGNATURE_MODE", "off")
    os.environ.setdefault("CONVERSATION_PROVIDER_TWILIO_ENABLED", "true")
    os.environ.setdefault("CONVERSATION_PROVIDER_SENDGRID_ENABLED", "false")
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
    api_module.notifier_sender = StubNotifierSender(enabled=True, channel="email,sms,imessage")
    api_module.openclaw_sender = api_module.notifier_sender
    api_module.reset_runtime_state_for_tests()
    return TestClient(create_app())


def _admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post(f"{PREFIX}/admin/login", json={"password": "test-admin-pw"})
    assert login.status_code == 200
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_sms_dispatch(client: TestClient) -> None:
    upsert = client.post(
        f"{PREFIX}/invoices/upsert",
        json={
            "invoices": [
                {
                    "invoice_id": "inv-conv-001",
                    "creator_id": "creator-conv-001",
                    "creator_name": "Conversation Creator",
                    "creator_timezone": "UTC",
                    "contact_channel": "sms",
                    "contact_target": "+15555550123",
                    "currency": "USD",
                    "amount_due": 400,
                    "amount_paid": 0,
                    "issued_at": "2026-02-01",
                    "due_date": "2026-02-10"
                }
            ]
        },
    )
    assert upsert.status_code == 200

    dispatch = client.post(
        f"{PREFIX}/invoices/dispatch",
        json={
            "invoice_id": "inv-conv-001",
            "dispatched_at": "2026-02-10T00:00:00Z",
            "channels": ["sms"],
            "recipient_phone": "+15555550123",
        },
    )
    assert dispatch.status_code == 200


def test_twilio_inbound_creates_thread_and_autoreply() -> None:
    client = _client(autoreply_enabled=True)
    _seed_sms_dispatch(client)

    inbound = client.post(
        f"{PREFIX}/webhooks/twilio/inbound",
        data={
            "MessageSid": "SM-inbound-001",
            "From": "+15555550123",
            "Body": "Hey can you send me the status?",
        },
    )
    assert inbound.status_code == 200, inbound.text
    data = inbound.json()
    assert data["accepted"] is True
    assert data["deduped"] is False

    admin_headers = _admin_headers(client)
    threads_resp = client.get(f"{PREFIX}/admin/conversations", headers=admin_headers)
    assert threads_resp.status_code == 200
    threads = threads_resp.json()["items"]
    assert len(threads) == 1
    assert threads[0]["creator_name"] == "Conversation Creator"
    assert threads[0]["auto_reply_count"] == 1

    detail_resp = client.get(f"{PREFIX}/admin/conversations/{data['thread_id']}", headers=admin_headers)
    assert detail_resp.status_code == 200
    messages = detail_resp.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["direction"] == "inbound"
    assert messages[1]["direction"] == "outbound"


def test_risky_content_forces_handoff() -> None:
    client = _client(autoreply_enabled=True)
    _seed_sms_dispatch(client)

    inbound = client.post(
        f"{PREFIX}/webhooks/twilio/inbound",
        data={
            "MessageSid": "SM-inbound-legal-001",
            "From": "+15555550123",
            "Body": "I will contact my lawyer and file a dispute.",
        },
    )
    assert inbound.status_code == 200
    thread_id = inbound.json()["thread_id"]

    admin_headers = _admin_headers(client)
    detail_resp = client.get(f"{PREFIX}/admin/conversations/{thread_id}", headers=admin_headers)
    assert detail_resp.status_code == 200
    thread = detail_resp.json()["thread"]
    messages = detail_resp.json()["messages"]
    assert thread["status"] == "human_handoff"
    assert len(messages) == 1


def test_agent_scope_can_suggest_and_execute_reply() -> None:
    client = _client(autoreply_enabled=True)
    _seed_sms_dispatch(client)

    inbound = client.post(
        f"{PREFIX}/webhooks/twilio/inbound",
        data={
            "MessageSid": "SM-agent-001",
            "From": "+15555550123",
            "Body": "Can you help me with payment details?",
        },
    )
    assert inbound.status_code == 200
    thread_id = inbound.json()["thread_id"]

    broker_payload = create_broker_token(
        agent_id="creator-conversation",
        scopes=frozenset({"conversations:read", "conversations:reply"}),
        secret=api_module._settings.broker_token_secret,
        ttl_minutes=60,
    )
    token = encode_broker_token(broker_payload, secret=api_module._settings.broker_token_secret)
    headers = {"Authorization": f"Bearer {token}"}

    suggest = client.post(
        f"{PREFIX}/agent/conversations/{thread_id}/suggest-reply",
        headers=headers,
        json={"reply_text": "Here is your update.", "confidence": 0.92},
    )
    assert suggest.status_code == 200
    assert suggest.json()["approved"] is True

    execute = client.post(
        f"{PREFIX}/agent/conversations/{thread_id}/execute-action",
        headers=headers,
        json={"action": "send_reply", "reply_text": "Here is your update.", "confidence": 0.92},
    )
    assert execute.status_code == 200
    assert execute.json()["status"] == "ok"


def test_twilio_webhooks_reject_when_provider_disabled() -> None:
    previous = _set_env("CONVERSATION_PROVIDER_TWILIO_ENABLED", "false")
    try:
        client = _client()
        _seed_sms_dispatch(client)
        inbound = client.post(
            f"{PREFIX}/webhooks/twilio/inbound",
            data={
                "MessageSid": "SM-disabled-001",
                "From": "+15555550123",
                "Body": "hello",
            },
        )
        assert inbound.status_code == 503
        assert "provider is disabled" in inbound.json()["detail"]
    finally:
        _restore_env("CONVERSATION_PROVIDER_TWILIO_ENABLED", previous)


def test_bluebubbles_inbound_and_status_flow() -> None:
    prev_enabled = _set_env("CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED", "true")
    prev_mode = _set_env("CONVERSATION_WEBHOOK_SIGNATURE_MODE", "off")
    try:
        client = _client()
        _seed_sms_dispatch(client)

        inbound = client.post(
            f"{PREFIX}/webhooks/bluebubbles/inbound",
            json={
                "guid": "BB-msg-001",
                "handle": "+15555550123",
                "text": "Need my invoice update",
                "chatGuid": "BB-chat-001",
                "isFromMe": False,
            },
        )
        assert inbound.status_code == 200
        inbound_data = inbound.json()
        assert inbound_data["accepted"] is True
        thread_id = inbound_data["thread_id"]

        admin_headers = _admin_headers(client)
        reply = client.post(
            f"{PREFIX}/admin/conversations/{thread_id}/reply",
            headers=admin_headers,
            json={"body_text": "Your invoice is still open, and we can help with timing."},
        )
        assert reply.status_code == 200
        provider_message_id = reply.json()["provider_message_id"]
        assert isinstance(provider_message_id, str)

        status = client.post(
            f"{PREFIX}/webhooks/bluebubbles/status",
            json={
                "guid": provider_message_id,
                "status": "delivered",
            },
        )
        assert status.status_code == 200
        assert status.json()["updated"] is True
        assert status.json()["delivery_state"] == "delivered"

        detail = client.get(f"{PREFIX}/admin/conversations/{thread_id}", headers=admin_headers)
        assert detail.status_code == 200
        messages = detail.json()["messages"]
        assert messages[-1]["delivery_state"] == "delivered"
        assert detail.json()["thread"]["channel"] == "imessage"
    finally:
        _restore_env("CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED", prev_enabled)
        _restore_env("CONVERSATION_WEBHOOK_SIGNATURE_MODE", prev_mode)


def test_bluebubbles_signature_enforce_rejects_unsigned_requests() -> None:
    prev_enabled = _set_env("CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED", "true")
    prev_mode = _set_env("CONVERSATION_WEBHOOK_SIGNATURE_MODE", "enforce")
    prev_secret = _set_env("BLUEBUBBLES_WEBHOOK_SECRET", "test-bluebubbles-secret")
    try:
        client = _client()
        _seed_sms_dispatch(client)
        inbound = client.post(
            f"{PREFIX}/webhooks/bluebubbles/inbound",
            json={
                "guid": "BB-msg-unsigned-001",
                "handle": "+15555550123",
                "text": "hello",
            },
        )
        assert inbound.status_code == 401
    finally:
        _restore_env("CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED", prev_enabled)
        _restore_env("CONVERSATION_WEBHOOK_SIGNATURE_MODE", prev_mode)
        _restore_env("BLUEBUBBLES_WEBHOOK_SECRET", prev_secret)
