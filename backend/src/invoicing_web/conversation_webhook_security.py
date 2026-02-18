from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Mapping

from .config import Settings

TWILIO_SDK_AVAILABLE = True
try:
    from twilio.request_validator import RequestValidator
except ModuleNotFoundError:
    TWILIO_SDK_AVAILABLE = False
    RequestValidator = None  # type: ignore[assignment]


class ConversationWebhookVerification:
    def __init__(self, *, verified: bool, reason: str | None = None) -> None:
        self.verified = verified
        self.reason = reason


def _normalize_header_value(headers: Mapping[str, str], key: str) -> str | None:
    value = headers.get(key)
    if value is None:
        lowered_key = key.lower()
        for header_key, header_value in headers.items():
            if header_key.lower() == lowered_key:
                value = header_value
                break
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def verify_twilio_signature(
    *,
    settings: Settings,
    url: str,
    form_data: Mapping[str, str],
    headers: Mapping[str, str],
) -> ConversationWebhookVerification:
    mode = settings.conversation_webhook_signature_mode
    if mode == "off":
        return ConversationWebhookVerification(verified=True)

    auth_token = settings.twilio_auth_token.strip()
    if not auth_token:
        return ConversationWebhookVerification(verified=False, reason="twilio_auth_token_missing")

    provided = _normalize_header_value(headers, "X-Twilio-Signature")
    if provided is None:
        return ConversationWebhookVerification(verified=False, reason="signature_missing")

    if not TWILIO_SDK_AVAILABLE:
        return ConversationWebhookVerification(verified=False, reason="twilio_sdk_missing")

    validator = RequestValidator(auth_token)  # type: ignore[operator]
    if not validator.validate(url=url, params=dict(form_data), signature=provided):
        return ConversationWebhookVerification(verified=False, reason="signature_mismatch")

    return ConversationWebhookVerification(verified=True)


def verify_bluebubbles_signature(
    *,
    settings: Settings,
    body: bytes,
    headers: Mapping[str, str],
) -> ConversationWebhookVerification:
    mode = settings.conversation_webhook_signature_mode
    if mode == "off":
        return ConversationWebhookVerification(verified=True)

    configured = settings.bluebubbles_webhook_secret.strip()
    if not configured:
        return ConversationWebhookVerification(verified=False, reason="bluebubbles_webhook_secret_missing")

    provided = (
        _normalize_header_value(headers, "X-EROS-BlueBubbles-Signature")
        or _normalize_header_value(headers, "X-BlueBubbles-Signature")
    )
    if provided is None:
        return ConversationWebhookVerification(verified=False, reason="signature_missing")

    timestamp = (
        _normalize_header_value(headers, "X-EROS-Webhook-Timestamp")
        or _normalize_header_value(headers, "X-Signature-Timestamp")
        or _normalize_header_value(headers, "X-BlueBubbles-Timestamp")
    )
    if timestamp:
        signed_payload = f"{timestamp}.{body.decode('utf-8', errors='replace')}".encode("utf-8")
    else:
        signed_payload = body

    digest = hmac.new(configured.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected_hex = digest.hex()
    expected_b64 = base64.b64encode(digest).decode("utf-8")

    normalized_provided = provided.strip()
    if normalized_provided.startswith("sha256="):
        normalized_provided = normalized_provided.split("=", 1)[1]

    valid = (
        hmac.compare_digest(expected_hex, normalized_provided)
        or hmac.compare_digest(expected_b64, normalized_provided)
    )
    if not valid:
        return ConversationWebhookVerification(verified=False, reason="signature_mismatch")

    return ConversationWebhookVerification(verified=True)


def verify_sendgrid_signature(
    *,
    settings: Settings,
    headers: Mapping[str, str],
) -> ConversationWebhookVerification:
    mode = settings.conversation_webhook_signature_mode
    if mode == "off":
        return ConversationWebhookVerification(verified=True)

    configured = settings.sendgrid_inbound_secret.strip()
    if not configured:
        return ConversationWebhookVerification(verified=False, reason="sendgrid_inbound_secret_missing")

    provided = _normalize_header_value(headers, "X-EROS-SendGrid-Token")
    if provided is None:
        return ConversationWebhookVerification(verified=False, reason="signature_missing")

    if not hmac.compare_digest(configured, provided):
        return ConversationWebhookVerification(verified=False, reason="signature_mismatch")

    return ConversationWebhookVerification(verified=True)


def webhook_timestamp_within_window(*, headers: Mapping[str, str], max_age_seconds: int) -> ConversationWebhookVerification:
    timestamp_header = (
        _normalize_header_value(headers, "X-Webhook-Timestamp")
        or _normalize_header_value(headers, "X-EROS-Webhook-Timestamp")
        or _normalize_header_value(headers, "X-Twilio-Request-Timestamp")
        or _normalize_header_value(headers, "X-Signature-Timestamp")
    )
    if timestamp_header is None:
        return ConversationWebhookVerification(verified=True)

    try:
        event_epoch = int(timestamp_header)
    except ValueError:
        return ConversationWebhookVerification(verified=False, reason="timestamp_invalid")

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if abs(now_epoch - event_epoch) > max(0, max_age_seconds):
        return ConversationWebhookVerification(verified=False, reason="timestamp_out_of_window")

    return ConversationWebhookVerification(verified=True)
