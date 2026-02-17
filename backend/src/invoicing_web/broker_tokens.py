from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class BrokerTokenError(ValueError):
    """Raised when broker agent tokens are invalid, expired, or lack required scopes."""


@dataclass(frozen=True, slots=True)
class BrokerTokenPayload:
    agent_id: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    token_id: str


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def create_broker_token(
    *,
    agent_id: str,
    scopes: frozenset[str],
    secret: str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> BrokerTokenPayload:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl_minutes)
    token_id = secrets.token_urlsafe(16)
    return BrokerTokenPayload(
        agent_id=agent_id,
        scopes=scopes,
        issued_at=issued_at,
        expires_at=expires_at,
        token_id=token_id,
    )


def encode_broker_token(payload: BrokerTokenPayload, *, secret: str) -> str:
    if not secret:
        raise BrokerTokenError("broker token secret is empty")

    payload_json = json.dumps(
        {
            "agent_id": payload.agent_id,
            "exp": int(payload.expires_at.timestamp()),
            "iat": int(payload.issued_at.timestamp()),
            "jti": payload.token_id,
            "scopes": sorted(payload.scopes),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_broker_token(
    token: str,
    *,
    secret: str,
    required_scope: str | None = None,
    now: datetime | None = None,
) -> BrokerTokenPayload:
    if not token or "." not in token:
        raise BrokerTokenError("invalid token format")
    if not secret:
        raise BrokerTokenError("broker token secret is empty")

    payload_b64, signature = token.rsplit(".", 1)
    expected = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise BrokerTokenError("token signature mismatch")

    try:
        payload_obj = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BrokerTokenError("token payload decoding failed") from exc

    agent_id = str(payload_obj.get("agent_id", "")).strip()
    if not agent_id:
        raise BrokerTokenError("token agent_id missing")

    try:
        exp = int(payload_obj["exp"])
    except Exception as exc:  # noqa: BLE001
        raise BrokerTokenError("token expiration missing") from exc

    try:
        iat = int(payload_obj["iat"])
    except Exception as exc:  # noqa: BLE001
        raise BrokerTokenError("token issued_at missing") from exc

    token_id = str(payload_obj.get("jti", "")).strip()
    if not token_id:
        raise BrokerTokenError("token jti missing")

    raw_scopes = payload_obj.get("scopes")
    if not isinstance(raw_scopes, list):
        raise BrokerTokenError("token scopes missing or invalid")
    scopes = frozenset(str(s) for s in raw_scopes)

    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)

    reference_now = now or datetime.now(timezone.utc)
    if expires_at <= reference_now:
        raise BrokerTokenError("token expired")

    if required_scope is not None and required_scope not in scopes:
        raise BrokerTokenError(
            f"token missing required scope: {required_scope}"
        )

    return BrokerTokenPayload(
        agent_id=agent_id,
        scopes=scopes,
        issued_at=issued_at,
        expires_at=expires_at,
        token_id=token_id,
    )
