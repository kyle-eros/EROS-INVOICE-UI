from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from invoicing_web.broker_tokens import (
    BrokerTokenError,
    create_broker_token,
    decode_broker_token,
    encode_broker_token,
)


def test_broker_token_round_trip() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    scopes = frozenset({"invoices:read", "reminders:read"})
    payload = create_broker_token(
        agent_id="invoice-monitor",
        scopes=scopes,
        secret="broker-secret-456",
        ttl_minutes=60,
        now=now,
    )
    token = encode_broker_token(payload, secret="broker-secret-456")

    decoded = decode_broker_token(
        token,
        secret="broker-secret-456",
        required_scope="invoices:read",
        now=now + timedelta(minutes=30),
    )

    assert decoded.agent_id == "invoice-monitor"
    assert decoded.scopes == scopes
    assert decoded.issued_at == now
    assert decoded.expires_at == now + timedelta(minutes=60)
    assert decoded.token_id == payload.token_id


def test_broker_token_expired() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_broker_token(
        agent_id="invoice-monitor",
        scopes=frozenset({"invoices:read"}),
        secret="broker-secret-456",
        ttl_minutes=1,
        now=now,
    )
    token = encode_broker_token(payload, secret="broker-secret-456")

    with pytest.raises(BrokerTokenError, match="token expired"):
        decode_broker_token(
            token,
            secret="broker-secret-456",
            now=now + timedelta(minutes=2),
        )


def test_broker_token_signature_mismatch() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_broker_token(
        agent_id="invoice-monitor",
        scopes=frozenset({"invoices:read"}),
        secret="broker-secret-456",
        ttl_minutes=60,
        now=now,
    )
    token = encode_broker_token(payload, secret="broker-secret-456")

    with pytest.raises(BrokerTokenError, match="token signature mismatch"):
        decode_broker_token(token, secret="wrong-secret", now=now)


def test_broker_token_scope_enforcement() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_broker_token(
        agent_id="invoice-monitor",
        scopes=frozenset({"invoices:read"}),
        secret="broker-secret-456",
        ttl_minutes=60,
        now=now,
    )
    token = encode_broker_token(payload, secret="broker-secret-456")

    with pytest.raises(BrokerTokenError, match="token missing required scope: reminders:run"):
        decode_broker_token(
            token,
            secret="broker-secret-456",
            required_scope="reminders:run",
            now=now,
        )


def test_broker_token_invalid_format() -> None:
    with pytest.raises(BrokerTokenError, match="invalid token format"):
        decode_broker_token("bad-token", secret="broker-secret-456")
