from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .config import Settings


@dataclass(frozen=True)
class WebhookSignatureVerification:
    verified: bool
    reason: str | None = None


def _normalize_signature(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("sha256="):
        return normalized.removeprefix("sha256=").strip().lower()
    return normalized.lower()


def _stripe_header_parts(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for chunk in value.split(","):
        key, _, item = chunk.partition("=")
        key = key.strip()
        item = item.strip()
        if key and item:
            parsed[key] = item
    return parsed


def _extract_signature_inputs(provider: str, headers: Mapping[str, str]) -> tuple[str | None, str | None]:
    if provider == "stripe":
        stripe_signature = headers.get("Stripe-Signature")
        if stripe_signature:
            parts = _stripe_header_parts(stripe_signature)
            return parts.get("t"), parts.get("v1")

    timestamp = (
        headers.get("X-Webhook-Timestamp")
        or headers.get("X-Signature-Timestamp")
    )
    signature = (
        headers.get("X-Webhook-Signature")
        or headers.get("X-Signature")
    )
    return timestamp, signature


def verify_payment_webhook_signature(
    *,
    settings: Settings,
    provider: str,
    body: bytes,
    headers: Mapping[str, str],
    now: datetime | None = None,
) -> WebhookSignatureVerification:
    mode = settings.payment_webhook_signature_mode
    if mode == "off":
        return WebhookSignatureVerification(verified=True)

    secret = settings.webhook_secret_for_provider(provider)
    if not secret:
        return WebhookSignatureVerification(verified=False, reason="webhook_secret_missing")

    timestamp_text, signature_text = _extract_signature_inputs(provider, headers)
    if not timestamp_text:
        return WebhookSignatureVerification(verified=False, reason="timestamp_missing")
    if not signature_text:
        return WebhookSignatureVerification(verified=False, reason="signature_missing")

    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return WebhookSignatureVerification(verified=False, reason="timestamp_invalid")

    current_time = now or datetime.now(timezone.utc)
    current_epoch = int(current_time.timestamp())
    max_age = max(0, settings.payment_webhook_signature_max_age_seconds)
    if abs(current_epoch - timestamp) > max_age:
        return WebhookSignatureVerification(verified=False, reason="timestamp_out_of_window")

    normalized_signature = _normalize_signature(signature_text)
    if normalized_signature is None:
        return WebhookSignatureVerification(verified=False, reason="signature_invalid")

    signing_payload = f"{timestamp}.".encode("utf-8") + body
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signing_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(normalized_signature, expected_signature):
        return WebhookSignatureVerification(verified=False, reason="signature_mismatch")

    return WebhookSignatureVerification(verified=True)
