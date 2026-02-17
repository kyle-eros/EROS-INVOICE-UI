from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
from invoicing_web.creator_tokens import CreatorTokenPayload, encode_creator_token
from invoicing_web.main import create_app
from invoicing_web.openclaw import StubOpenClawSender


def _client() -> TestClient:
    os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
    api_module.task_store.reset()
    api_module.openclaw_sender = StubOpenClawSender(enabled=True, channel="email,sms")
    # Recreate settings to pick up env var
    from invoicing_web.config import get_settings
    api_module._settings = get_settings()
    return TestClient(create_app())


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/v1/invoicing/admin/login", json={"password": "test-admin-pw"})
    assert resp.status_code == 200
    return resp.json()["session_token"]


def _seed_creator_invoices(client: TestClient, creator_id: str = "creator-001", creator_name: str = "Test Creator") -> None:
    """Create and dispatch an invoice for a creator so they have data."""
    upsert = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={
            "invoices": [
                {
                    "invoice_id": f"inv-{creator_id}",
                    "creator_id": creator_id,
                    "creator_name": creator_name,
                    "creator_timezone": "UTC",
                    "contact_channel": "email",
                    "contact_target": "test@example.com",
                    "currency": "USD",
                    "amount_due": 500.0,
                    "amount_paid": 0.0,
                    "issued_at": "2026-02-01",
                    "due_date": "2026-03-01",
                }
            ]
        },
    )
    assert upsert.status_code == 200

    dispatch = client.post(
        "/api/v1/invoicing/invoices/dispatch",
        json={
            "invoice_id": f"inv-{creator_id}",
            "dispatched_at": "2026-02-10T00:00:00Z",
            "channels": ["email"],
            "recipient_email": "test@example.com",
        },
    )
    assert dispatch.status_code == 200


def test_admin_login_and_session() -> None:
    client = _client()
    admin_token = _admin_token(client)
    assert admin_token

    session_resp = client.get(
        "/api/v1/invoicing/admin/session",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_resp.status_code == 200
    assert session_resp.json()["authenticated"] is True


def test_admin_wrong_password_rejected() -> None:
    client = _client()
    resp = client.post("/api/v1/invoicing/admin/login", json={"password": "wrong-pw"})
    assert resp.status_code == 401


def test_admin_endpoints_require_auth() -> None:
    client = _client()

    # No auth header
    assert client.get("/api/v1/invoicing/passkeys").status_code == 401
    assert client.post("/api/v1/invoicing/passkeys/generate", json={"creator_id": "c1", "creator_name": "N"}).status_code == 401
    assert client.post("/api/v1/invoicing/passkeys/revoke", json={"creator_id": "c1"}).status_code == 401
    assert client.get("/api/v1/invoicing/admin/session").status_code == 401

    # Invalid token
    headers = {"Authorization": "Bearer invalid-token"}
    assert client.get("/api/v1/invoicing/passkeys", headers=headers).status_code == 401


def test_generate_and_lookup_round_trip() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    gen_resp = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-001", "creator_name": "Alice"},
        headers=headers,
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["creator_id"] == "creator-001"
    assert gen_data["creator_name"] == "Alice"
    raw_passkey = gen_data["passkey"]
    assert len(raw_passkey) > 20
    assert gen_data["display_prefix"] == raw_passkey[:6]

    lookup_resp = client.post(
        "/api/v1/invoicing/auth/lookup",
        json={"passkey": raw_passkey},
    )
    assert lookup_resp.status_code == 200
    assert lookup_resp.json()["creator_id"] == "creator-001"
    assert lookup_resp.json()["creator_name"] == "Alice"

    # Bad passkey
    bad_resp = client.post("/api/v1/invoicing/auth/lookup", json={"passkey": "wrong"})
    assert bad_resp.status_code == 401


def test_login_confirm_session_flow() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    gen_resp = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-002", "creator_name": "Bob"},
        headers=headers,
    )
    raw_passkey = gen_resp.json()["passkey"]

    confirm_resp = client.post(
        "/api/v1/invoicing/auth/confirm",
        json={"passkey": raw_passkey},
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["creator_id"] == "creator-002"
    assert confirm_data["creator_name"] == "Bob"
    assert "session_token" in confirm_data
    assert "expires_at" in confirm_data


def test_revoke_blocks_login() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    gen_resp = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-003", "creator_name": "Charlie"},
        headers=headers,
    )
    raw_passkey = gen_resp.json()["passkey"]

    # Confirm works before revoke
    confirm_resp = client.post("/api/v1/invoicing/auth/confirm", json={"passkey": raw_passkey})
    assert confirm_resp.status_code == 200

    # Revoke
    revoke_resp = client.post(
        "/api/v1/invoicing/passkeys/revoke",
        json={"creator_id": "creator-003"},
        headers=headers,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    # Lookup now fails
    lookup_resp = client.post("/api/v1/invoicing/auth/lookup", json={"passkey": raw_passkey})
    assert lookup_resp.status_code == 401

    # List should be empty
    list_resp = client.get("/api/v1/invoicing/passkeys", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()["creators"]) == 0


def test_session_grants_invoice_access() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    _seed_creator_invoices(client, "creator-004", "Dana")

    gen_resp = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-004", "creator_name": "Dana"},
        headers=headers,
    )
    raw_passkey = gen_resp.json()["passkey"]

    confirm_resp = client.post("/api/v1/invoicing/auth/confirm", json={"passkey": raw_passkey})
    session_token = confirm_resp.json()["session_token"]

    invoices_resp = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert invoices_resp.status_code == 200
    data = invoices_resp.json()
    assert data["creator_id"] == "creator-004"
    assert data["creator_name"] == "Dana"
    assert len(data["invoices"]) == 1
    assert data["invoices"][0]["invoice_id"] == "inv-creator-004"


def test_expired_session_rejected() -> None:
    client = _client()

    # Manually craft an expired token
    expired_payload = CreatorTokenPayload(
        creator_id="creator-005",
        expires_at=datetime(2000, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    expired_token = encode_creator_token(expired_payload, secret="dev-session-secret")

    resp = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401


def test_rate_limiting() -> None:
    client = _client()

    # Exhaust rate limit with bad passkeys (5 attempts)
    for _ in range(5):
        resp = client.post("/api/v1/invoicing/auth/lookup", json={"passkey": "bad-key"})
        assert resp.status_code == 401

    # 6th attempt should be rate limited
    resp = client.post("/api/v1/invoicing/auth/lookup", json={"passkey": "bad-key"})
    assert resp.status_code == 429


def test_admin_login_and_passkey_crud() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # List is empty initially
    list_resp = client.get("/api/v1/invoicing/passkeys", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["creators"] == []

    # Generate two
    client.post("/api/v1/invoicing/passkeys/generate", json={"creator_id": "c1", "creator_name": "A"}, headers=headers)
    client.post("/api/v1/invoicing/passkeys/generate", json={"creator_id": "c2", "creator_name": "B"}, headers=headers)

    list_resp = client.get("/api/v1/invoicing/passkeys", headers=headers)
    assert len(list_resp.json()["creators"]) == 2

    # Revoke one
    client.post("/api/v1/invoicing/passkeys/revoke", json={"creator_id": "c1"}, headers=headers)

    list_resp = client.get("/api/v1/invoicing/passkeys", headers=headers)
    assert len(list_resp.json()["creators"]) == 1
    assert list_resp.json()["creators"][0]["creator_id"] == "c2"

    # Revoke non-existent returns revoked=False
    revoke_resp = client.post("/api/v1/invoicing/passkeys/revoke", json={"creator_id": "no-such"}, headers=headers)
    assert revoke_resp.json()["revoked"] is False
