from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from invoicing_web.creator_tokens import (
    CreatorTokenError,
    create_creator_token,
    decode_creator_token,
    encode_creator_token,
)


def test_creator_token_round_trip() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_creator_token(
        creator_id="creator-001",
        secret="secret-123",
        ttl_minutes=60,
        now=now,
    )
    token = encode_creator_token(payload, secret="secret-123")

    decoded = decode_creator_token(token, secret="secret-123", now=now + timedelta(minutes=30))

    assert decoded.creator_id == "creator-001"
    assert decoded.expires_at == now + timedelta(minutes=60)
    assert decoded.session_version == 1


def test_creator_token_round_trip_with_session_version() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_creator_token(
        creator_id="creator-001",
        secret="secret-123",
        ttl_minutes=60,
        now=now,
        session_version=9,
    )
    token = encode_creator_token(payload, secret="secret-123")

    decoded = decode_creator_token(token, secret="secret-123", now=now + timedelta(minutes=1))
    assert decoded.session_version == 9


def test_creator_token_expired() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_creator_token(
        creator_id="creator-001",
        secret="secret-123",
        ttl_minutes=1,
        now=now,
    )
    token = encode_creator_token(payload, secret="secret-123")

    with pytest.raises(CreatorTokenError, match="token expired"):
        decode_creator_token(token, secret="secret-123", now=now + timedelta(minutes=2))


def test_creator_token_signature_mismatch() -> None:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)
    payload = create_creator_token(
        creator_id="creator-001",
        secret="secret-123",
        ttl_minutes=60,
        now=now,
    )
    token = encode_creator_token(payload, secret="secret-123")

    with pytest.raises(CreatorTokenError, match="token signature mismatch"):
        decode_creator_token(token, secret="wrong-secret", now=now)


def test_creator_token_invalid_format() -> None:
    with pytest.raises(CreatorTokenError, match="invalid token format"):
        decode_creator_token("bad-token", secret="secret-123")
