from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class CreatorTokenError(ValueError):
    """Raised when creator magic-link tokens are invalid or expired."""


@dataclass(frozen=True)
class CreatorTokenPayload:
    creator_id: str
    expires_at: datetime
    session_version: int = 1


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def create_creator_token(
    *,
    creator_id: str,
    secret: str,
    ttl_minutes: int,
    now: datetime | None = None,
    session_version: int = 1,
) -> CreatorTokenPayload:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl_minutes)
    if session_version < 1:
        raise CreatorTokenError("token session version must be >= 1")
    return CreatorTokenPayload(
        creator_id=creator_id,
        expires_at=expires_at,
        session_version=session_version,
    )


def encode_creator_token(payload: CreatorTokenPayload, *, secret: str) -> str:
    if not secret:
        raise CreatorTokenError("creator token secret is empty")

    payload_json = json.dumps(
        {
            "creator_id": payload.creator_id,
            "exp": int(payload.expires_at.timestamp()),
            "sv": int(payload.session_version),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_creator_token(token: str, *, secret: str, now: datetime | None = None) -> CreatorTokenPayload:
    if not token or "." not in token:
        raise CreatorTokenError("invalid token format")
    if not secret:
        raise CreatorTokenError("creator token secret is empty")

    payload_b64, signature = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise CreatorTokenError("token signature mismatch")

    try:
        payload_obj = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CreatorTokenError("token payload decoding failed") from exc

    creator_id = str(payload_obj.get("creator_id", "")).strip()
    if not creator_id:
        raise CreatorTokenError("token creator_id missing")

    try:
        exp = int(payload_obj["exp"])
    except Exception as exc:  # noqa: BLE001
        raise CreatorTokenError("token expiration missing") from exc

    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    reference_now = now or datetime.now(timezone.utc)
    if expires_at <= reference_now:
        raise CreatorTokenError("token expired")

    try:
        session_version = int(payload_obj.get("sv", 1))
    except Exception as exc:  # noqa: BLE001
        raise CreatorTokenError("token session version invalid") from exc
    if session_version < 1:
        raise CreatorTokenError("token session version invalid")

    return CreatorTokenPayload(
        creator_id=creator_id,
        expires_at=expires_at,
        session_version=session_version,
    )
