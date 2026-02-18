from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from invoicing_web import api as api_module
from invoicing_web.auth_store import SQLALCHEMY_AVAILABLE
from invoicing_web.creator_tokens import CreatorTokenPayload, encode_creator_token
from invoicing_web.main import create_app
from invoicing_web.openclaw import StubOpenClawSender


def _client() -> TestClient:
    os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
    api_module.openclaw_sender = StubOpenClawSender(enabled=True, channel="email,sms")
    # Recreate settings to pick up env var
    from invoicing_web.config import get_settings
    api_module._settings = get_settings()
    api_module.auth_repo = api_module._create_auth_repo(api_module._settings)
    api_module.reset_runtime_state_for_tests()
    return TestClient(create_app())


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/v1/invoicing/admin/login", json={"password": "test-admin-pw"})
    assert resp.status_code == 200
    return resp.json()["session_token"]


def _invoice_detail_payload() -> dict:
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
                "gross_total": 1000.00,
                "split_percent": 50.0,
            }
        ],
    }


def _seed_creator_invoices(
    client: TestClient,
    creator_id: str = "creator-001",
    creator_name: str = "Test Creator",
    *,
    include_detail: bool = False,
) -> None:
    """Create and dispatch an invoice for a creator so they have data."""
    invoice_payload = {
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
    if include_detail:
        invoice_payload["detail"] = _invoice_detail_payload()

    upsert = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={
            "invoices": [invoice_payload]
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
    assert client.get("/api/v1/invoicing/admin/creators").status_code == 401
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
    assert data["invoices"][0]["issued_at"] == "2026-02-01"
    assert data["invoices"][0]["has_pdf"] is False


def test_creator_pdf_requires_session() -> None:
    client = _client()
    resp = client.get("/api/v1/invoicing/me/invoices/inv-creator-004/pdf")
    assert resp.status_code == 401


def test_creator_pdf_access_flow() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    _seed_creator_invoices(client, "creator-006", "Erin", include_detail=True)

    gen_resp = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-006", "creator_name": "Erin"},
        headers=headers,
    )
    session_token = client.post("/api/v1/invoicing/auth/confirm", json={"passkey": gen_resp.json()["passkey"]}).json()["session_token"]

    invoices_resp = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert invoices_resp.status_code == 200
    invoice_item = invoices_resp.json()["invoices"][0]
    assert invoice_item["invoice_id"] == "inv-creator-006"
    assert invoice_item["has_pdf"] is True

    pdf_resp = client.get(
        "/api/v1/invoicing/me/invoices/inv-creator-006/pdf",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"].startswith("application/pdf")
    assert 'inline; filename="inv-creator-006.pdf"' in pdf_resp.headers["content-disposition"]
    assert pdf_resp.content.startswith(b"%PDF")


def test_creator_pdf_owner_and_detail_checks() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    _seed_creator_invoices(client, "creator-007", "Finley", include_detail=True)
    _seed_creator_invoices(client, "creator-008", "Harper", include_detail=False)

    gen_owner = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-007", "creator_name": "Finley"},
        headers=headers,
    )
    owner_token = client.post("/api/v1/invoicing/auth/confirm", json={"passkey": gen_owner.json()["passkey"]}).json()["session_token"]

    gen_other = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-009", "creator_name": "Iris"},
        headers=headers,
    )
    other_token = client.post("/api/v1/invoicing/auth/confirm", json={"passkey": gen_other.json()["passkey"]}).json()["session_token"]

    forbidden_resp = client.get(
        "/api/v1/invoicing/me/invoices/inv-creator-007/pdf",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden_resp.status_code == 404

    missing_detail_resp = client.get(
        "/api/v1/invoicing/me/invoices/inv-creator-008/pdf",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert missing_detail_resp.status_code == 404

    owner_missing_detail = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-008", "creator_name": "Harper"},
        headers=headers,
    )
    owner_missing_detail_token = client.post(
        "/api/v1/invoicing/auth/confirm",
        json={"passkey": owner_missing_detail.json()["passkey"]},
    ).json()["session_token"]

    detail_resp = client.get(
        "/api/v1/invoicing/me/invoices/inv-creator-008/pdf",
        headers={"Authorization": f"Bearer {owner_missing_detail_token}"},
    )
    assert detail_resp.status_code == 422


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


def test_admin_creator_directory_reports_portal_readiness() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    _seed_creator_invoices(client, "creator-ready", "Ready Creator")

    upsert = client.post(
        "/api/v1/invoicing/invoices/upsert",
        json={
            "invoices": [
                {
                    "invoice_id": "inv-creator-unready",
                    "creator_id": "creator-unready",
                    "creator_name": "Unready Creator",
                    "creator_timezone": "UTC",
                    "contact_channel": "email",
                    "contact_target": "unready@example.com",
                    "currency": "USD",
                    "amount_due": 250.0,
                    "amount_paid": 0.0,
                    "issued_at": "2026-02-05",
                    "due_date": "2026-03-05",
                }
            ]
        },
    )
    assert upsert.status_code == 200

    directory = client.get("/api/v1/invoicing/admin/creators", headers=headers)
    assert directory.status_code == 200
    payload = directory.json()
    creators = {item["creator_id"]: item for item in payload["creators"]}

    assert creators["creator-ready"]["invoice_count"] == 1
    assert creators["creator-ready"]["dispatched_invoice_count"] == 1
    assert creators["creator-ready"]["ready_for_portal"] is True

    assert creators["creator-unready"]["invoice_count"] == 1
    assert creators["creator-unready"]["dispatched_invoice_count"] == 0
    assert creators["creator-unready"]["ready_for_portal"] is False


def test_regenerate_invalidates_existing_creator_sessions() -> None:
    client = _client()
    admin_token = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    _seed_creator_invoices(client, "creator-010", "June")

    first_passkey = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-010", "creator_name": "June"},
        headers=headers,
    ).json()["passkey"]

    first_session = client.post(
        "/api/v1/invoicing/auth/confirm",
        json={"passkey": first_passkey},
    ).json()["session_token"]

    first_access = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {first_session}"},
    )
    assert first_access.status_code == 200

    second_passkey = client.post(
        "/api/v1/invoicing/passkeys/generate",
        json={"creator_id": "creator-010", "creator_name": "June"},
        headers=headers,
    ).json()["passkey"]

    stale_access = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {first_session}"},
    )
    assert stale_access.status_code == 401
    assert "session revoked" in stale_access.json()["detail"]

    second_session = client.post(
        "/api/v1/invoicing/auth/confirm",
        json={"passkey": second_passkey},
    ).json()["session_token"]

    renewed_access = client.get(
        "/api/v1/invoicing/me/invoices",
        headers={"Authorization": f"Bearer {second_session}"},
    )
    assert renewed_access.status_code == 200


def test_client_ip_uses_trusted_proxy_rules() -> None:
    original_trust = os.environ.get("TRUST_PROXY_HEADERS")
    original_trusted_ips = os.environ.get("TRUSTED_PROXY_IPS")
    try:
        os.environ["TRUST_PROXY_HEADERS"] = "false"
        os.environ["TRUSTED_PROXY_IPS"] = "testclient,127.0.0.1"
        client = _client()

        # With trust disabled, XFF should be ignored and attempts should aggregate to one client.
        for index in range(5):
            resp = client.post(
                "/api/v1/invoicing/auth/lookup",
                json={"passkey": "bad-key"},
                headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
            )
            assert resp.status_code == 401
        blocked = client.post(
            "/api/v1/invoicing/auth/lookup",
            json={"passkey": "bad-key"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        assert blocked.status_code == 429

        os.environ["TRUST_PROXY_HEADERS"] = "true"
        os.environ["TRUSTED_PROXY_IPS"] = "testclient,127.0.0.1"
        client = _client()

        # With trust enabled and a trusted proxy source, XFF should be honored.
        for _ in range(5):
            resp = client.post(
                "/api/v1/invoicing/auth/lookup",
                json={"passkey": "bad-key"},
                headers={"X-Forwarded-For": "198.51.100.10"},
            )
            assert resp.status_code == 401
        blocked = client.post(
            "/api/v1/invoicing/auth/lookup",
            json={"passkey": "bad-key"},
            headers={"X-Forwarded-For": "198.51.100.10"},
        )
        assert blocked.status_code == 429

        different_forwarded_ip = client.post(
            "/api/v1/invoicing/auth/lookup",
            json={"passkey": "bad-key"},
            headers={"X-Forwarded-For": "198.51.100.11"},
        )
        assert different_forwarded_ip.status_code == 401
    finally:
        if original_trust is None:
            os.environ.pop("TRUST_PROXY_HEADERS", None)
        else:
            os.environ["TRUST_PROXY_HEADERS"] = original_trust
        if original_trusted_ips is None:
            os.environ.pop("TRUSTED_PROXY_IPS", None)
        else:
            os.environ["TRUSTED_PROXY_IPS"] = original_trusted_ips


def test_rate_limit_persists_when_auth_store_uses_database() -> None:
    if not SQLALCHEMY_AVAILABLE:
        pytest.skip("sqlalchemy is not installed in this test runtime")

    original_auth_backend = os.environ.get("AUTH_STORE_BACKEND")
    original_database_url = os.environ.get("DATABASE_URL")
    db_name = f"/tmp/invoicing_auth_{uuid4().hex}.db"
    try:
        os.environ["AUTH_STORE_BACKEND"] = "postgres"
        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_name}"
        client = _client()

        for _ in range(5):
            resp = client.post("/api/v1/invoicing/auth/lookup", json={"passkey": "bad-key"})
            assert resp.status_code == 401

        # Simulate process restart by rebuilding settings/repo without resetting persisted state.
        from invoicing_web.config import get_settings
        api_module._settings = get_settings()
        api_module.auth_repo = api_module._create_auth_repo(api_module._settings)
        client_after_restart = TestClient(create_app())

        blocked = client_after_restart.post("/api/v1/invoicing/auth/lookup", json={"passkey": "bad-key"})
        assert blocked.status_code == 429
    finally:
        if original_auth_backend is None:
            os.environ.pop("AUTH_STORE_BACKEND", None)
        else:
            os.environ["AUTH_STORE_BACKEND"] = original_auth_backend
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
